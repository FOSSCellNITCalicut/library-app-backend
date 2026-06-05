from app.db.models.book import Book
from app.db.database import Base

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    String,
    ForeignKey,
    DateTime
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship
)

class BookCopy(Base):
    __tablename__ = "book_copies"

    item_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    biblio_id: Mapped[int] = mapped_column(
        ForeignKey(
            "books.biblio_id",
            ondelete="CASCADE"
        )
    )

    branch: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )
    
    # aquisition date will be useful
    acquisition_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    callnumber: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationship
    book: Mapped["Book"] = relationship(back_populates="copies")
