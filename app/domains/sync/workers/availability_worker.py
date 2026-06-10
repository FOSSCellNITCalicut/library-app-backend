import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Book, BookCopy, SyncState
from app.domains.sync.queue_service import enqueue_metadata_job
from app.integrations.koha.client import KohaClient, KohaServerError


logger = logging.getLogger(__name__)

NEW_DISCOVERY_PRIORITY = 10

EXPECTED_ITEM_KEYS = {
    "item_id",
    "biblio_id",
    "home_library_id",
}


class AvailabilitySchemaError(Exception):
    """Raised when the Koha /items response is missing expected fields."""


def _parse_koha_date(value) -> date | None:
    # If Koha ever returns acquisition_date in an unexpected format, we want to avoid crashing the whole worker.
    
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class AvailabilityWorker:
    def __init__(self, client: KohaClient):
        self.client = client

        if not isinstance(self.client, KohaClient):
            raise ValueError("AvailabilityWorker requires a KohaClient instance")

    async def get_sync_state(self, *, session: AsyncSession) -> SyncState:
        state = await session.get(SyncState, 1)
        
        if state is None:
            state = SyncState(current_page=1)
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
            raise AvailabilitySchemaError(f"Koha /items response missing expected fields: {sorted(missing)}")

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

        # Add the book with placeholder title if it doesn't exist
        # If there is a conflict on biblio_id, we assume the existing row has a real title and do nothing
        book_stmt = insert(Book).values(biblio_id=biblio_id, title="Unknown Title")
        book_stmt = book_stmt.on_conflict_do_nothing()
        book_stmt = book_stmt.returning(Book.biblio_id)
        book_result = await session.execute(book_stmt)
        
        inserted_biblio_id = book_result.scalar_one_or_none()

        # Upsert the BookCopy record for this item
        copy_stmt = insert(BookCopy).values(
            item_id=item_id,
            biblio_id=biblio_id,
            branch=branch,
            callnumber=item.get("callnumber"),
            acquisition_date=_parse_koha_date(item.get("acquisition_date")),
            status=self.compute_availability(item),
            last_seen_at=now,
        )

        # On conflict, update all fields except item_id, and set last_seen_at to now.
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

        # If we inserted a new biblio_id, enqueue a metadata job with elevated priority to fetch the title and other details
        if inserted_biblio_id is not None:
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
                raise

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

    async def _skip_stuck_page(self) -> int:
        """
        Advance the cursor past the current page so the worker stops spinning
        on a page that keeps failing.
        
        Returns the page number that was skipped (before the advance) so the caller can log it.
        The caller is responsible for resetting any in-memory failure counters.
        """
        async with AsyncSessionLocal() as session:
            state = await self.get_sync_state(session=session)
            old_page = state.current_page
            state.current_page += 1
            state.last_completed_at = datetime.now(timezone.utc)
            await session.commit()
        
        return old_page

    async def run(self) -> None:
        # For any exception, wait twice the normal delay before retrying up to 5 times before skipping the page
        # We want to be resilient to transient issues with the Koha server, but if there is a persistent problem with a 
        # specific page, we shall skip it to avoid blocking the entire sync process
        consecutive_500s = 0

        while True:
            try:
                await self.sync_next_page()
                consecutive_500s = 0

            except KohaServerError as e:
                logger.error("Koha 5xx in availability loop: %s", e)
                consecutive_500s += 1

                if consecutive_500s >= settings.MAX_AVAILABILITY_500_RETRIES:
                    old_page = await self._skip_stuck_page()
                    logger.error(
                        "Koha returned %s consecutive errors on page %s, advancing to page %s",
                        consecutive_500s, old_page, old_page + 1,
                    )
                    consecutive_500s = 0
                else:
                    await asyncio.sleep(settings.AVAILABILITY_WORKER_DELAY * 2)

                continue

            except AvailabilitySchemaError as e:
                logger.error("Schema validation failed, halting sync: %s", e)

                # If the schema is not what we expect, it could either be a transient issue or a long-term change.
                # Back off for a while before retrying, but keep the worker alive to avoid losing the sync state.
                # Sync state doesn't have retry counts or error tracking unlike metadata queue
                await asyncio.sleep(settings.AVAILABILITY_WORKER_DELAY * 2)
                continue

            except Exception as e:
                logger.exception("Unexpected error in availability loop: %s", e)
                consecutive_500s += 1

                if consecutive_500s >= settings.MAX_AVAILABILITY_500_RETRIES:
                    old_page = await self._skip_stuck_page()
                    logger.error(
                        "Koha returned %s consecutive errors on page %s, advancing to page %s",
                        consecutive_500s, old_page, old_page + 1,
                    )
                    consecutive_500s = 0
                else:
                    await asyncio.sleep(settings.AVAILABILITY_WORKER_DELAY * 2)

                continue

            # If syncing was successful, wait before the next page to avoid hammering the Koha server
            await asyncio.sleep(settings.AVAILABILITY_WORKER_DELAY)
