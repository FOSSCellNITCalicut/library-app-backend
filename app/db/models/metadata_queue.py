from app.db.database import Base

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Integer,
    Text,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column


class MetadataQueue(Base):
    __tablename__ = "metadata_queue"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    biblio_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    status: Mapped[str] = mapped_column(
        Text,
        default="pending"
    )

    available_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False
    )
