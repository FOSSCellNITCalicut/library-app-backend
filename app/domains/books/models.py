from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    String,
    Text,
    Integer,
    ForeignKey,
    DateTime
)
from sqlalchemy.dialects.postgresql import ARRAY

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship
)

DATABASE_URL = "postgresql://postgres:nitc@localhost:5432/library_app"

engine  = create_engine (DATABASE_URL)

SessionLocal = sessionmaker (
    bind=engine,
    autoflush=False,
    autocommit = False
)

class Base(DeclarativeBase):
    pass

class Book(Base):
    __tablename__ = "books"

    #koha id
    biblio_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True
    )

    # metadata
    title: Mapped[str] = mapped_column (
        Text,
        nullable=False
    )
        #authors can be multiple
    author: Mapped[list[str] | None] = mapped_column (
        ARRAY(String),
        nullable=True
    )
        #isbn can be multiple
    isbn: Mapped[list[str] | None] = mapped_column (
        ARRAY(String),
        nullable=True,
        index=True
    )

    publisher: Mapped[str | None] = mapped_column (
        String(255)
    )

    published_year: Mapped[int | None] = mapped_column (
        Integer
    )

    edition: Mapped[str | None] = mapped_column (
        String(100)
    )


    # Enrichment
    description: Mapped[str | None] = mapped_column (
        Text
    )

    cover_url: Mapped[str | None] = mapped_column (
        Text
    )
        # categories can be multiple
    categories: Mapped[list[str] | None] = mapped_column (
        ARRAY(String)
    )


    # Aggregates
    total_copies: Mapped[int] = mapped_column (
        Integer,
        default=0
    )

    available_copies: Mapped[int] = mapped_column (
        Integer,
        default=0
    )

    lib_copies: Mapped[int] = mapped_column (
        Integer,
        default=0
    )

    mat_copies: Mapped[int] = mapped_column (
        Integer,
        default=0
    )

    # metadata sync
    metadata_synced_at: Mapped[datetime | None] = mapped_column (
        DateTime(timezone=True)
    )

    availability_synced_at: Mapped[datetime | None] = mapped_column (
        DateTime(timezone=True)
    )

    # audit fields
    created_at: Mapped[datetime | None] = mapped_column (
        DateTime(timezone=True),
        default= lambda: datetime.now(timezone.utc)
    )

    updated_at: Mapped[datetime | None] = mapped_column (
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    #Relationship with BookCopy
    copies: Mapped[list["BookCopy"]] = relationship (
        back_populates="book",
        cascade="all, delete-orphan"  
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
    acquisition_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    callnumber: Mapped[str | None] = mapped_column(
        String(255)
    )

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
    book: Mapped["Book"] = relationship(
        back_populates="copies"
    )