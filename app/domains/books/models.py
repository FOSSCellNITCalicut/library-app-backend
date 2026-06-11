from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Book(Base):
    __tablename__ = "books"

    biblio_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    isbn: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True, index=True)
    publisher: Mapped[str | None] = mapped_column(String(255))
    published_year: Mapped[int | None] = mapped_column(Integer)
    edition: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    total_copies: Mapped[int] = mapped_column(Integer, default=0)
    available_copies: Mapped[int] = mapped_column(Integer, default=0)
    lib_copies: Mapped[int] = mapped_column(Integer, default=0)
    mat_copies: Mapped[int] = mapped_column(Integer, default=0)
    metadata_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    copies: Mapped[list["BookCopy"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_books_search_vector", "search_vector", postgresql_using="gin"),
    )


class BookCopy(Base):
    __tablename__ = "book_copies"

    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    biblio_id: Mapped[int] = mapped_column(
        ForeignKey("books.biblio_id", ondelete="CASCADE")
    )
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    acquisition_date: Mapped[date | None] = mapped_column(Date)
    callnumber: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    book: Mapped["Book"] = relationship(back_populates="copies")
