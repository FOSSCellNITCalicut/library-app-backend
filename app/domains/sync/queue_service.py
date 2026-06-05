from sqlalchemy import case, func

from app.db.models.metadata_queue import MetadataQueue

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

async def enqueue_metadata_job(*, session: AsyncSession, biblio_id: int, priority: int = 0):
    """
    Enqueue a metadata job for processing.
    """
    stmt = insert(MetadataQueue).values(
        biblio_id=biblio_id,
        priority=priority,
        status="pending"
    )
    
    stmt = stmt.on_conflict_do_update(
        index_elements=[MetadataQueue.biblio_id],
        set_={
            "priority": func.least(MetadataQueue.priority + priority, 100),
                
            "status":
                case(
                    (MetadataQueue.status == "completed", "pending"),
                    else_=MetadataQueue.status
                )
        }
    )

    await session.execute(stmt)
