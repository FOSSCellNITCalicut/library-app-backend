"""Business logic layer for the Books domain.

Called by:  router.py
Calls:      repository.py

Returns clean dict data validated against Pydantic schemas.
"""

from app.domains.books.schemas import (
    BookDetailSchema,
    BookListResponse,
    BookSummarySchema,
)


class ValidationError(Exception):
    pass


class BookNotFoundError(Exception):
    def __init__(self, biblio_id: int):
        self.biblio_id = biblio_id
        super().__init__(f"Book with biblio_id={biblio_id} not found")


MAX_PER_PAGE = 100
ALLOWED_SORT_FIELDS = {"title", "author", "published_year", "publisher"}


class BookService:
    def __init__(self, repository):
        self._repository = repository
        self._cache = None

    async def search_by_isbn(self, isbn):
        if not isbn or not isbn.strip():
            raise ValidationError("ISBN must not be empty")

        results = await self._repository.search_by_isbn(isbn.strip())
        items = [self._to_summary(r) for r in results]

        return BookListResponse(
            items=items, page=1, per_page=len(items) or 1, total=len(items),
        ).model_dump()

    async def search_books(self, query, page=1, per_page=20):
        if not query or not query.strip():
            raise ValidationError("Search query must not be empty")

        if page < 1:
            raise ValidationError("Page must be >= 1")

        if per_page < 1:
            raise ValidationError("per_page must be >= 1")
        per_page = min(per_page, MAX_PER_PAGE)

        offset = (page - 1) * per_page
        results, total_count = await self._repository.search_books(
            query=query, offset=offset, limit=per_page,
        )

        items = [self._to_summary(r) for r in results]

        return BookListResponse(
            items=items, page=page, per_page=per_page, total=total_count,
        ).model_dump()

    async def browse_books(self, page=1, per_page=20, sort_by="title", sort_order="asc"):
        if page < 1:
            raise ValidationError("Page must be >= 1")

        if per_page < 1:
            raise ValidationError("per_page must be >= 1")
        per_page = min(per_page, MAX_PER_PAGE)

        self._validate_sort_params(sort_by, sort_order)

        offset = (page - 1) * per_page
        results, total_count = await self._repository.browse_books(
            offset=offset, limit=per_page,
            sort_by=sort_by, sort_order=sort_order,
        )

        items = [self._to_summary(r) for r in results]
        base = BookListResponse(
            items=items, page=page, per_page=per_page, total=total_count,
        ).model_dump()

        base["sort_by"] = sort_by
        base["sort_order"] = sort_order
        return base

    async def get_book_details(self, biblio_id):
        book = await self._repository.get_book_by_id(biblio_id)
        if book is None:
            raise BookNotFoundError(biblio_id)

        return BookDetailSchema.model_validate(book).model_dump()

    def _to_summary(self, book):
        return BookSummarySchema.model_validate(book)

    def _validate_sort_params(self, sort_by, sort_order):
        if sort_by not in ALLOWED_SORT_FIELDS:
            raise ValidationError(
                f"sort_by must be one of: {', '.join(sorted(ALLOWED_SORT_FIELDS))}"
            )
        if sort_order not in {"asc", "desc"}:
            raise ValidationError("sort_order must be 'asc' or 'desc'")
