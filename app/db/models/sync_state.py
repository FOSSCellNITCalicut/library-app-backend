from app.db.database import Base

from datetime import datetime

from sqlalchemy import TIMESTAMP, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column


class SyncState(Base):
    __tablename__ = "sync_state"

    worker_name: Mapped[str] = mapped_column(
        Text,
        primary_key=True
    )

    current_page: Mapped[int] = mapped_column(
        Integer,
        default=1
    )

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True)
    )