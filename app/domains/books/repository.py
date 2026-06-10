from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.book import Book
from app.db.models.book_copy import BookCopy
from app.domains.books.schemas import BookCopySchema, BookDetailSchema, BookSummarySchema

# Module-level sort map
SORT_MAP = {
    "title": func.lower(Book.title).asc(),
    "date_added": Book.created_at.desc(),
}


class BooksRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    async def search_books(
        self,
        query: str,
        page: int,
        per_page: int,
    ) -> tuple[list[BookSummarySchema], int]:
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
            .offset((page - 1) * per_page)
            .limit(per_page)
        )

        rows = (await self.db.execute(stmt)).mappings().all()
        total = rows[0]["total_count"] if rows else 0
        items = [BookSummarySchema(**row) for row in rows]
        return (items, total)

    async def browse_books(
        self,
        page: int,
        per_page: int,
        sort_by: str | None = None,
        branch: str | None = None,
    ) -> tuple[list[BookSummarySchema], int]:
        """Browse the full catalogue with optional sort and branch filter.

        Returns a (items, total_count) tuple.
        """
        order_clause = SORT_MAP.get(sort_by, Book.biblio_id.asc())

        stmt = select(
            Book.biblio_id,
            Book.title,
            Book.authors,
            Book.edition,
            Book.cover_url,
            Book.available_copies,
            Book.total_copies,
            Book.lib_copies,
            Book.mat_copies,
            func.count().over().label("total_count"),
        )

        if branch == "LIB":
            stmt = stmt.where(Book.lib_copies > 0)
        elif branch == "MAT":
            stmt = stmt.where(Book.mat_copies > 0)

        stmt = stmt.order_by(order_clause).offset((page - 1) * per_page).limit(per_page)

        rows = (await self.db.execute(stmt)).mappings().all()
        total = rows[0]["total_count"] if rows else 0
        items = [BookSummarySchema(**row) for row in rows]
        return (items, total)

    async def get_book_by_id(self, biblio_id: int) -> BookDetailSchema | None:
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
        book = (await self.db.execute(stmt)).scalar_one_or_none()

        if book is None:
            return None

        return BookDetailSchema.model_validate(book)
