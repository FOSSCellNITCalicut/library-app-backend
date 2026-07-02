import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.models import CatalogBook
from app.domains.books.service import BookService, BookNotFoundError
from app.domains.catalog.schemas import CatalogBookDetailSchema, CatalogBooksResponse

logger = logging.getLogger(__name__)


class CatalogService:
    def __init__(self, db: AsyncSession, book_service: BookService):
        self.db = db
        self.book_service = book_service

    async def get_books_for_course(self, course_id: str) -> CatalogBooksResponse:
        # 1. Fetch all catalog rows for this course_id
        result = await self.db.execute(
            select(CatalogBook.biblio_id, CatalogBook.search_string)
            .where(CatalogBook.course_id == course_id)
        )
        rows = result.all()

        if not rows:
            return CatalogBooksResponse(course_id=course_id, books=[])

        search_string_by_biblio_id = {row.biblio_id: row.search_string for row in rows}

        # 2. Fetch book details sequentially (shared AsyncSession isn't safe for concurrent calls)
        books = []
        for biblio_id, search_string in search_string_by_biblio_id.items():
            try:
                book = await self.book_service.get_book_details(biblio_id=biblio_id)
            except BookNotFoundError:
                logger.warning("Book %s for course %s not found, skipping", biblio_id, course_id)
                continue
            except Exception:
                logger.exception("Error fetching book %s for course %s, skipping", biblio_id, course_id)
                continue
            book_dict = book.model_dump() if hasattr(book, "model_dump") else dict(book)
            books.append(
                CatalogBookDetailSchema(
                    **book_dict,
                    search_string=search_string,
                )
            )

        return CatalogBooksResponse(course_id=course_id, books=books)
