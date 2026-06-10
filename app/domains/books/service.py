"""Business logic layer for the Books domain.

Called by:  router.py
Calls:      repository.py

Returns clean dict data that can be converted into Pydantic schemas.
"""


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

        return {
            "items": results,
            "page": 1,
            "per_page": len(results) or 1,
            "total": len(results),
        }

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

        return {
            "items": results,
            "page": page,
            "per_page": per_page,
            "total": total_count,
        }

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

        return {
            "items": results,
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }

    async def get_book_details(self, biblio_id):
        book = await self._repository.get_book_by_id(biblio_id)
        if book is None:
            raise BookNotFoundError(biblio_id)

        copies = await self._repository.get_book_copies(biblio_id)
        isbn_val = book.get("isbn")
        if isinstance(isbn_val, str):
            isbn_val = [isbn_val]

        return {
            "biblio_id": book["biblio_id"],
            "title": book["title"],
            "authors": book.get("authors", []),
            "publisher": book.get("publisher"),
            "published_year": book.get("published_year"),
            "isbn": isbn_val,
            "categories": book.get("categories", []),
            "description": book.get("description"),
            "copies": [
                {
                    "branch": c["branch"],
                    "status": c["status"],
                    "callnumber": c.get("call_number"),
                }
                for c in copies
            ],
        }

    def _validate_sort_params(self, sort_by, sort_order):
        if sort_by not in ALLOWED_SORT_FIELDS:
            raise ValidationError(
                f"sort_by must be one of: {', '.join(sorted(ALLOWED_SORT_FIELDS))}"
            )
        if sort_order not in {"asc", "desc"}:
            raise ValidationError("sort_order must be 'asc' or 'desc'")
