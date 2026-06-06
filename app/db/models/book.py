from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy import (
    BigInteger,
    Index,
    String,
    Text,
    Integer,
    DateTime
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship
)

from app.db.database import Base

class Book(Base):
    __tablename__ = "books"

    # Koha ID - unique identifier for a bibliographic record
    biblio_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    # Metadata
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    
    # Multiple authors can exist for a book (co-authors, editors)
    authors: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True
    )
    
    # Multiple ISBNs can exist for a book (different editions, formats)
    isbn: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        index=True
    )

    publisher: Mapped[str | None] = mapped_column(String(255))

    published_year: Mapped[int | None] = mapped_column(Integer)

    edition: Mapped[str | None] = mapped_column(String(100))

    # Enrichment
    description: Mapped[str | None] = mapped_column(Text)

    cover_url: Mapped[str | None] = mapped_column(Text)
    
    # Categories can be multiple
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(String))


    # Aggregates
    total_copies: Mapped[int] = mapped_column(Integer, default=0)

    available_copies: Mapped[int] = mapped_column(Integer, default=0)

    lib_copies: Mapped[int] = mapped_column(Integer, default=0)

    mat_copies: Mapped[int] = mapped_column(Integer, default=0)

    # metadata sync
    metadata_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    availability_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # audit fields
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationship with BookCopy
    copies: Mapped[list["BookCopy"]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan"  
    )

    # GIN index
    __table_args__ = (
        Index(
            "ix_books_search_vector",
            "search_vector",
            postgresql_using="gin"
        ),
    )
