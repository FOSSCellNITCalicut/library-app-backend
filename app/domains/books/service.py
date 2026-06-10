"""Business logic layer for the Books domain.

Called by:  router.py
Calls:      repository.py

Returns clean dict data validated against Pydantic schemas.
"""

from app.domains.books.schemas import (
    BookCopySchema,
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

        copies = await self._repository.get_book_copies(biblio_id)
        isbn_val = book.get("isbn")
        if isinstance(isbn_val, str):
            isbn_val = [isbn_val]

        return BookDetailSchema(
            biblio_id=book["biblio_id"],
            title=book["title"],
            authors=book.get("authors"),
            isbn=isbn_val,
            publisher=book.get("publisher"),
            published_year=book.get("published_year"),
            edition=None,
            description=book.get("description"),
            cover_url=None,
            categories=book.get("categories"),
            total_copies=len(copies),
            available_copies=sum(1 for c in copies if c.get("status") == "available"),
            lib_copies=0,
            mat_copies=0,
            availability_synced_at=None,
            copies=[
                BookCopySchema(
                    item_id=0,
                    branch=c["branch"],
                    callnumber=c.get("call_number"),
                    status=c["status"],
                    acquisition_date=None,
                )
                for c in copies
            ] or [],
        ).model_dump()

    def _to_summary(self, r):
        return BookSummarySchema(
            biblio_id=r["biblio_id"],
            title=r["title"],
            authors=r.get("authors"),
            edition=None,
            cover_url=None,
            available_copies=0,
            total_copies=0,
            lib_copies=0,
            mat_copies=0,
        )

    def _validate_sort_params(self, sort_by, sort_order):
        if sort_by not in ALLOWED_SORT_FIELDS:
            raise ValidationError(
                f"sort_by must be one of: {', '.join(sorted(ALLOWED_SORT_FIELDS))}"
            )
        if sort_order not in {"asc", "desc"}:
            raise ValidationError("sort_order must be 'asc' or 'desc'")
