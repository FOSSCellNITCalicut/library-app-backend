import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Book, MetadataQueue
from app.db.models.metadata_queue import JobStatus
from app.domains.sync.marc_parser import marc_parser
from app.integrations.koha.client import KohaClient, koha_client


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
                MetadataQueue.status == JobStatus.PENDING,
                MetadataQueue.available_at <= now,
            )
            .order_by(MetadataQueue.priority.desc(), MetadataQueue.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True) # Lock the selected row to prevent other workers from claiming it simultaneously (not useful now)
        )
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()

        if job:
            job.status = JobStatus.IN_PROGRESS
            await session.flush() # Save it immediately to lock the row for other workers (not useful now)

        return job

    async def update_book_metadata(
        self,
        *,
        session: AsyncSession,
        biblio_id: int,
        metadata: dict,
    ) -> bool:
        book: Book | None = await session.get(Book, biblio_id)
        if not book:
            logger.warning("Book biblio_id=%s not found, skipping", biblio_id)
            return False

        if metadata.get("title"):
            book.title = metadata["title"]
        if metadata.get("authors"):
            book.authors = metadata["authors"]
        if metadata.get("isbns"):
            book.isbn = metadata["isbns"]
        if metadata.get("publisher"):
            book.publisher = metadata["publisher"]
        if metadata.get("categories"):
            book.categories = metadata["categories"]
        if metadata.get("year"):
            book.published_year = metadata["year"]

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
        
        new_status = JobStatus.FAILED if give_up else JobStatus.PENDING
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
            job.status = new_status
            job.available_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
            if give_up:
                job.finished_at = datetime.now(timezone.utc)
            
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
            raise MetadataSchemaError(f"Koha /biblios/{job.biblio_id} returned no usable response")

        metadata = marc_parser.parse_marc_to_dict(response)

        if not metadata.get("title"):
            raise MetadataSchemaError(f"MARC for biblio_id={job.biblio_id} had no 245$a (title)")

        await self.update_book_metadata(session=session, biblio_id=job.biblio_id, metadata=metadata)

        job.status = JobStatus.COMPLETED
        job.finished_at = datetime.now(timezone.utc)

    async def run(self) -> None:
        while True:
            async with AsyncSessionLocal() as session:
                try:
                    job = await self.claim_job(session=session)
                    if job is None:
                        await asyncio.sleep(settings.METADATA_WORKER_DELAY)
                        continue

                    try:
                        await self.process_job(session=session, job=job)
                        await session.commit()
                        logger.info("Metadata job for biblio_id=%s completed", job.biblio_id)

                    except Exception as process_error:
                        biblio_id = job.biblio_id
                        previous_retry_count = job.retry_count
                        error_message = repr(process_error)
                        
                        await self._record_failure(
                            biblio_id=biblio_id,
                            previous_retry_count=previous_retry_count,
                            error=error_message,
                        )
                except Exception as e:
                    logger.exception("Unexpected error in metadata loop: %s", e)

            await asyncio.sleep(settings.METADATA_WORKER_DELAY)
