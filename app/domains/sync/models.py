import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Index,
    Integer,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class MetadataQueue(Base):
    __tablename__ = "metadata_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    biblio_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=JobStatus.PENDING,
    )
    available_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_metadata_queue_status_finished_at", "status", "finished_at"),
    )


class SyncState(Base):
    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1, server_default="1"
    )
    current_page: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    last_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
