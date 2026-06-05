import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import configure_logging
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Book, MetadataQueue
from app.integrations.koha.client import KohaClient, koha_client


configure_logging()
logger = logging.getLogger(__name__)


MAX_BACKOFF_SECONDS = 3600
ERROR_TRUNCATE_LENGTH = 1000


class MetadataSchemaError(Exception):
    """Raised when the parsed MARC dict is missing required fields."""


class MetadataWorker:
    def __init__(self, client: KohaClient | None = None):
        self.client = client or koha_client

    async def claim_job(self, *, session: AsyncSession) -> MetadataQueue | None:
        now = datetime.now(timezone.utc)
        stmt = (
            select(MetadataQueue)
            .where(
                MetadataQueue.status == "pending",
                MetadataQueue.available_at <= now,
            )
            .order_by(MetadataQueue.priority.desc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    def _find_marc_field(self, fields: list, code: str) -> dict | None:
        if not fields:
            return None
        for entry in fields:
            if isinstance(entry, dict) and code in entry:
                value = entry[code]
                if isinstance(value, dict):
                    return value
        return None

    def _marc_subfield(self, field_data: dict | None, code: str) -> str | None:
        if not field_data:
            return None
        subfields = field_data.get("subfields") or []
        for sub in subfields:
            if not isinstance(sub, dict):
                continue
            if code in sub:
                value = sub[code]
                if value:
                    return str(value).strip()
            if sub.get("code") == code:
                value = sub.get("value")
                if value:
                    return str(value).strip()
        return None

    def parse_marc_to_dict(self, marc_data) -> dict:
        """
        Extract a small subset of fields from MARC-in-JSON. Tolerates missing
        fields by returning whatever we can find.
        """
        if not isinstance(marc_data, dict):
            return {}

        fields = marc_data.get("fields") or []

        title = self._marc_subfield(self._find_marc_field(fields, "245"), "a")
        author = (
            self._marc_subfield(self._find_marc_field(fields, "100"), "a")
            or self._marc_subfield(self._find_marc_field(fields, "110"), "a")
            or self._marc_subfield(self._find_marc_field(fields, "111"), "a")
        )
        isbn = self._marc_subfield(self._find_marc_field(fields, "020"), "a")
        publisher = (
            self._marc_subfield(self._find_marc_field(fields, "264"), "b")
            or self._marc_subfield(self._find_marc_field(fields, "260"), "b")
        )

        return {
            "title": title,
            "author": [author] if author else None,
            "isbn": [isbn] if isbn else None,
            "publisher": publisher,
        }

    async def update_book_metadata(
        self,
        *,
        session: AsyncSession,
        biblio_id: int,
        metadata: dict,
    ) -> bool:
        book = await session.get(Book, biblio_id)
        if not book:
            logger.warning("Book biblio_id=%s not found, skipping", biblio_id)
            return False

        if metadata.get("title"):
            book.title = metadata["title"]
        if metadata.get("author"):
            book.author = metadata["author"]
        if metadata.get("isbn"):
            book.isbn = metadata["isbn"]
        if metadata.get("publisher"):
            book.publisher = metadata["publisher"]

        book.metadata_synced_at = datetime.now(timezone.utc)
        return True

    async def _record_failure(
        self,
        *,
        biblio_id: int,
        previous_retry_count: int,
        error: str,
    ) -> None:
        new_retry_count = previous_retry_count + 1
        give_up = new_retry_count >= settings.MAX_METADATA_RETRIES
        backoff_seconds = min(2 ** new_retry_count, MAX_BACKOFF_SECONDS)
        new_status = "failed" if give_up else "pending"
        truncated_error = (error or "")[:ERROR_TRUNCATE_LENGTH]

        async with AsyncSessionLocal() as session:
            stmt = select(MetadataQueue).where(MetadataQueue.biblio_id == biblio_id)
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            if job is None:
                logger.error(
                    "Failed to find metadata_queue row for biblio_id=%s during failure recording",
                    biblio_id,
                )
                return

            job.retry_count = new_retry_count
            job.last_error = truncated_error
            job.status = new_status
            job.available_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
            await session.commit()

        if give_up:
            logger.error(
                "Metadata job for biblio_id=%s dead-lettered after %s retries: %s",
                biblio_id,
                new_retry_count,
                truncated_error,
            )
        else:
            logger.warning(
                "Metadata job for biblio_id=%s failed (retry %s/%s), backoff=%ss: %s",
                biblio_id,
                new_retry_count,
                settings.MAX_METADATA_RETRIES,
                backoff_seconds,
                truncated_error,
            )

    async def process_job(self, *, session: AsyncSession, job: MetadataQueue) -> None:
        response = await self.client.get_metadata(job.biblio_id)
        if response is None:
            raise MetadataSchemaError(
                f"Koha /biblios/{job.biblio_id} returned no usable response"
            )

        metadata = self.parse_marc_to_dict(response)
        if not metadata.get("title"):
            raise MetadataSchemaError(
                f"MARC for biblio_id={job.biblio_id} had no 245$a (title)"
            )

        await self.update_book_metadata(
            session=session,
            biblio_id=job.biblio_id,
            metadata=metadata,
        )

        job.status = "completed"
        job.last_error = None

    async def run(self) -> None:
        try:
            while True:
                async with AsyncSessionLocal() as session:
                    try:
                        job = await self.claim_job(session=session)
                        if job is None:
                            await session.rollback()
                            await asyncio.sleep(settings.METADATA_WORKER_DELAY)
                            continue

                        try:
                            await self.process_job(session=session, job=job)
                            await session.commit()
                            logger.info(
                                "Metadata job for biblio_id=%s completed",
                                job.biblio_id,
                            )
                        except Exception as process_error:
                            biblio_id = job.biblio_id
                            previous_retry_count = job.retry_count
                            error_message = repr(process_error)
                            await session.rollback()
                            
                            await self._record_failure(
                                biblio_id=biblio_id,
                                previous_retry_count=previous_retry_count,
                                error=error_message,
                            )
                    except Exception as e:
                        logger.exception("Unexpected error in metadata loop: %s", e)
                        await session.rollback()

                await asyncio.sleep(settings.METADATA_WORKER_DELAY)
        except (KeyboardInterrupt, SystemExit):
            logger.info("MetadataWorker shutting down")
        finally:
            await self.client.aclose()


async def _main() -> None:
    worker = MetadataWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(_main())
