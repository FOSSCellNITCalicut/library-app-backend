import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import configure_logging
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Book, BookCopy, SyncState
from app.domains.sync.queue_service import enqueue_metadata_job
from app.integrations.koha.client import KohaClient, KohaServerError, koha_client


configure_logging()
logger = logging.getLogger(__name__)


WORKER_NAME = "availability"
NEW_DISCOVERY_PRIORITY = 10

EXPECTED_ITEM_KEYS = {
    "item_id",
    "biblio_id",
    "home_library_id",
}


class AvailabilitySchemaError(Exception):
    """Raised when the Koha /items response is missing expected fields."""


def _parse_koha_datetime(value) -> datetime | None:
    """
    Koha returns timestamps as ISO-8601 strings. asyncpg refuses raw strings
    for timestamptz columns, so normalise to a timezone-aware datetime here.
    """
    if value is None or isinstance(value, datetime):
        return value
    
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    
    return None


class AvailabilityWorker:
    def __init__(self, client: KohaClient | None = None):
        self.client = client or koha_client

    async def get_sync_state(self, *, session: AsyncSession) -> SyncState:
        stmt = select(SyncState).where(SyncState.worker_name == WORKER_NAME)
        result = await session.execute(stmt)
        state = result.scalar_one_or_none()

        if state is None:
            state = SyncState(
                worker_name=WORKER_NAME,
                current_page=1,
            )
            session.add(state)
            await session.flush()

        return state

    def compute_availability(self, item: dict) -> str:
        if not EXPECTED_ITEM_KEYS.issubset(item.keys()):
            return "Unknown"

        if (
            item.get("checked_out_date") is None
            and item.get("lost_status") == 0
            and item.get("damaged_status") == 0
            and item.get("not_for_loan_status") == 0
            and item.get("withdrawn") == 0
        ):
            return "Available"
        return "Not Available"

    def validate_page(self, response: list[dict]) -> None:
        if not response:
            return

        sample = response[0]
        missing = EXPECTED_ITEM_KEYS - sample.keys()
        if missing:
            raise AvailabilitySchemaError(
                f"Koha /items response missing expected fields: {sorted(missing)}"
            )

    async def process_item(self, *, session: AsyncSession, item: dict) -> bool:
        item_id = item.get("item_id")
        biblio_id = item.get("biblio_id")
        branch = item.get("home_library_id")

        if item_id is None or biblio_id is None or not branch:
            logger.warning(
                "Skipping item missing required fields: item_id=%s biblio_id=%s branch=%s",
                item_id,
                biblio_id,
                branch,
            )
            return False

        now = datetime.now(timezone.utc)

        book_stmt = insert(Book).values(biblio_id=biblio_id, title="Unknown Title")
        book_stmt = book_stmt.on_conflict_do_nothing()
        await session.execute(book_stmt)

        copy_stmt = insert(BookCopy).values(
            item_id=item_id,
            biblio_id=biblio_id,
            branch=branch,
            callnumber=item.get("callnumber"),
            acquisition_date=_parse_koha_datetime(item.get("acquisition_date")),
            status=self.compute_availability(item),
            last_seen_at=now,
        )

        copy_stmt = copy_stmt.on_conflict_do_update(
            index_elements=[BookCopy.item_id],
            set_={
                "branch": copy_stmt.excluded.branch,
                "callnumber": copy_stmt.excluded.callnumber,
                "acquisition_date": copy_stmt.excluded.acquisition_date,
                "status": copy_stmt.excluded.status,
                "last_seen_at": now,
            },
        )

        await session.execute(copy_stmt)

        await enqueue_metadata_job(
            session=session,
            biblio_id=biblio_id,
            priority=NEW_DISCOVERY_PRIORITY,
        )

        return True

    async def sync_next_page(self) -> None:
        async with AsyncSessionLocal() as session:
            state = await self.get_sync_state(session=session)

            try:
                response = await self.client.get_items(page=state.current_page)
            except KohaServerError as e:
                logger.error("Koha 5xx on page %s: %s", state.current_page, e)
                await session.rollback()
                return

            self.validate_page(response)

            if not response:
                logger.info("Wrapped around: resetting current_page to 1")
                state.current_page = 1
                state.last_completed_at = datetime.now(timezone.utc)
                await session.commit()
                return

            processed = 0
            for item in response:
                try:
                    if await self.process_item(session=session, item=item):
                        processed += 1
                except Exception as e:
                    logger.exception("Failed to process item %s: %s", item.get("item_id"), e)

            state.current_page += 1
            state.last_completed_at = datetime.now(timezone.utc)
            await session.commit()

            logger.info(
                "Synced page %s: processed=%s/%s",
                state.current_page - 1,
                processed,
                len(response),
            )

    async def run(self) -> None:
        consecutive_500s = 0
        try:
            while True:
                try:
                    await self.sync_next_page()
                    consecutive_500s = 0
                
                except AvailabilitySchemaError as e:
                    logger.error("Schema validation failed, halting sync: %s", e)
                    await asyncio.sleep(settings.AVAILABILITY_SYNC_DELAY * 6)
                    continue
                
                except Exception as e:
                    logger.exception("Unexpected error in availability loop: %s", e)
                    consecutive_500s += 1
                    if consecutive_500s >= settings.MAX_AVAILABILITY_500_RETRIES:
                        logger.error(
                            "Koha returned errors %s times in a row, backing off",
                            consecutive_500s,
                        )
                        await asyncio.sleep(settings.AVAILABILITY_SYNC_DELAY * 6)
                    else:
                        await asyncio.sleep(settings.AVAILABILITY_SYNC_DELAY)
                    continue

                await asyncio.sleep(settings.AVAILABILITY_SYNC_DELAY)
        except (KeyboardInterrupt, SystemExit):
            logger.info("AvailabilityWorker shutting down")
        finally:
            await self.client.aclose()


async def _main() -> None:
    worker = AvailabilityWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(_main())
