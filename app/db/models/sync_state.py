from app.db.database import Base

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column


class SyncState(Base):
    __tablename__ = "sync_state"

    # Not useful as of now, but could be used in the future to support multiple workers with different sync states.
    worker_name: Mapped[str] = mapped_column(
        Text,
        primary_key=True
    )

    current_page: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False
    )

    last_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
