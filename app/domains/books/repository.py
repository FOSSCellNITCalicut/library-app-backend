from __future__ import annotations

from sqlalchemy import any_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.books.models import Book, BookCopy
# schema validations are done in service

# Module-level sort map (according to service.py)
SORT_MAP = {
    "title": func.lower(Book.title),
    "authors": Book.authors,
    "published_year": Book.published_year,
    "publisher": Book.publisher,
}


class BooksRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    async def search_books(
        self,
        query: str,
        offset: int, # service passes offset and limit
        limit: int,
    ) -> tuple[list[dict], int]:
        """Full-text search over books.search_vector, ranked by relevance.

        Returns a (items, total_count) tuple. total_count is the number of
        matching rows across *all* pages, not just the current page.
        """
        ts_query = func.plainto_tsquery("english", query)
        rank_expr = func.ts_rank(Book.search_vector, ts_query)

        stmt = (
            select(
                Book.biblio_id,
                Book.title,
                Book.authors,
                Book.isbn,
                Book.edition,
                Book.cover_url,
                Book.available_copies,
                Book.total_copies,
                Book.lib_copies,
                Book.mat_copies,
                rank_expr.label("rank"),
                func.count().over().label("total_count"),
            )
            .where(Book.search_vector.op("@@")(ts_query))
            .order_by(rank_expr.desc())
            .offset(offset)
            .limit(limit)
        )

        rows = (await self.db.execute(stmt)).mappings().all()
        total = rows[0]["total_count"] if rows else 0
        # service will do the validation
        return (list(rows), total)

    async def browse_books(
        self,
        offset: int,
        limit: int,
        sort_by: str = "title",
        sort_order: str = "asc",
    ) -> tuple[list[dict], int]:
        """Browse the full catalogue with optional sort and branch filter.

        Returns a (items, total_count) tuple.
        """
        sort_col = SORT_MAP.get(sort_by, func.lower(Book.title))
        order_clause = sort_col.asc() if sort_order == "asc" else sort_col.desc()

        stmt = (
                select(
                Book.biblio_id,
                Book.title,
                Book.authors,
                Book.isbn,
                Book.edition,
                Book.cover_url,
                Book.available_copies,
                Book.total_copies,
                Book.lib_copies,
                Book.mat_copies,
                func.count().over().label("total_count"),
            )
            .order_by(order_clause)
            .offset(offset)
            .limit(limit)
        )

        # branch is not passed from service

        rows = (await self.db.execute(stmt)).mappings().all()
        total = rows[0]["total_count"] if rows else 0
        return (list(rows), total)

    async def get_book_by_id(self, biblio_id: int) -> Book | None:
        """Fetch a single book with all its physical copies.

        Uses selectinload so copies are fetched in a second targeted query
        rather than a cartesian-product JOIN, which keeps the result set compact.
        Returns None when biblio_id is not found.
        """
        stmt = (
            select(Book)
            .options(selectinload(Book.copies))
            .where(Book.biblio_id == biblio_id)
        )
        # service will do the validation
        return (await self.db.execute(stmt)).scalar_one_or_none()
    
    async def search_by_isbn(self, isbn: str) -> list[dict]:
        """Fetch book summaries by exact ISBN match."""
        stmt = (
            select(
                Book.biblio_id,
                Book.title,
                Book.authors,
                Book.edition,
                Book.cover_url,
                Book.available_copies,
                Book.total_copies,
                Book.lib_copies,
                Book.mat_copies,
            )
            .where(isbn == any_(Book.isbn))
        )
        
        rows = (await self.db.execute(stmt)).mappings().all()
        return list(rows)

    async def get_copies_by_biblio_id(self, biblio_id: int) -> list[BookCopy]:
        stmt = select(BookCopy).where(BookCopy.biblio_id == biblio_id)
        return list((await self.db.execute(stmt)).scalars().all())

