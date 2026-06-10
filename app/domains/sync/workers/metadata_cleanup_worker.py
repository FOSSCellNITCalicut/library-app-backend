import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete

from app.db.database import AsyncSessionLocal
from app.db.models.metadata_queue import JobStatus, MetadataQueue


logger = logging.getLogger(__name__)


class MetadataCleanupWorker:
    async def delete_old_jobs(self):
        # Define a cutoff time for old jobs (e.g., 1 day ago)
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=1)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(MetadataQueue)
                .where(
                    and_(
                        MetadataQueue.status.in_([JobStatus.COMPLETED, JobStatus.FAILED]),
                        MetadataQueue.finished_at < cutoff_time,
                    )
                )
                .returning(MetadataQueue.id),
            )
            await session.commit()
            deleted_count = len(result.all())
            
            if deleted_count:
                logger.info("Cleaned up %s old metadata queue jobs", deleted_count)

    async def run(self):
        while True:
            try:
                await self.delete_old_jobs()
            except Exception as e:
                logger.exception("Error during metadata cleanup: %s", e)

            await asyncio.sleep(3600) # Run cleanup every hour
