from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class CatalogBook(Base):
    __tablename__ = "catalog_books"

    course_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )

    biblio_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("books.biblio_id", ondelete="CASCADE"),
        primary_key=True,
    )
    
    search_string: Mapped[str | None] = mapped_column(
          Text, 
          nullable=True,
    )

    __table_args__ = (
        Index("ix_catalog_books_biblio_id", "biblio_id"),
    )

