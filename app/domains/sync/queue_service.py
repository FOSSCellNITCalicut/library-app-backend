from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sync.models import JobStatus, MetadataQueue


async def enqueue_metadata_job(*, session: AsyncSession, biblio_id: int, priority: int = 0) -> None:
    """
    Enqueue a metadata job for processing.

    Status rules on conflict (no-resurrect contract):
    - completed -> pending (data has gone stale, re-fetch)
    - pending -> pending (idempotent)
    - failed -> failed (dead-lettered; do NOT resurrect)

    Priority is still bumped for all rows on conflict (harmless for failed rows
    since they will never be claimed).
    """
    stmt = insert(MetadataQueue).values(
        biblio_id=biblio_id,
        priority=priority,
        status=JobStatus.PENDING,
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=[MetadataQueue.biblio_id],
        set_={
            "priority": func.least(MetadataQueue.priority + priority, 100),
            "status": case(
                (MetadataQueue.status == JobStatus.COMPLETED, JobStatus.PENDING),
                else_=MetadataQueue.status,
            ),
        },
    )

    await session.execute(stmt)
