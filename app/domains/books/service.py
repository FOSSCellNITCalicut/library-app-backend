"""Business logic layer for the Books domain.

Called by:  router.py
Calls:      repository.py

Returns validated Pydantic schema objects.
"""

from datetime import date, datetime, timezone

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert

from app.domains.books.models import Book, BookCopy
from app.domains.books.schemas import (
    BookDetailSchema,
    BookListResponse,
    BookSummarySchema,
)

from app.domains.books.schemas import BookAvailabilitySchema

from app.integrations.koha.client import koha_client


class ServiceValidationError(Exception):
    pass


class BookNotFoundError(Exception):
    def __init__(self, biblio_id: int):
        self.biblio_id = biblio_id
        super().__init__(f"Book with biblio_id={biblio_id} not found")


MAX_PER_PAGE = 100
ALLOWED_SORT_FIELDS = {"title", "authors", "published_year", "publisher"}

def _is_item_available(item: dict) -> bool:
    return (
        item.get("checked_out_date") is None
        and item.get("lost_status") == 0
        and item.get("damaged_status") == 0
        and item.get("not_for_loan_status") == 0
        and item.get("withdrawn") == 0
    )


def _parse_koha_date(value) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class BiblioNotFoundError(Exception):
    """Raised when Koha has no record for the given biblio_id, or is unreachable."""

    def __init__(self, biblio_id: int):
        self.biblio_id = biblio_id
        super().__init__(f"Koha returned no data for biblio_id={biblio_id}")


class BookService:
    def __init__(self, repository):
        self._repository = repository
        self._koha_client = koha_client
        self._cache = None # TODO: Implement caching layer for book details

    async def search_by_isbn(self, isbn) -> BookListResponse:
        if not isbn or not isbn.strip():
            raise ServiceValidationError("ISBN must not be empty")

        results = await self._repository.search_by_isbn(isbn.strip())
        items = self._to_summary(results)

        return BookListResponse(items=items, page=1, per_page=len(items) or 1, total=len(items))

    async def search_books(self, query, page=1, per_page=20, categories=None) -> BookListResponse:
        if not query or not query.strip():
            raise ServiceValidationError("Search query must not be empty")

        if page < 1:
            raise ServiceValidationError("Page must be >= 1")

        if per_page < 1:
            raise ServiceValidationError("per_page must be >= 1")
        per_page = min(per_page, MAX_PER_PAGE)

        offset = (page - 1) * per_page
        results, total_count = await self._repository.search_books(
            query=query, offset=offset, limit=per_page, categories=categories,
        )

        items = self._to_summary(results)

        # Get available categories for the search query
        available_categories = await self._repository.get_available_categories(query)

        return BookListResponse(
            items=items,
            page=page,
            per_page=per_page,
            total=total_count,
            available_categories=available_categories
        )

    async def browse_books(self, page=1, per_page=20, sort_by="title", sort_order="asc") -> BookListResponse:
        if page < 1:
            raise ServiceValidationError("Page must be >= 1")

        if per_page < 1:
            raise ServiceValidationError("per_page must be >= 1")
        per_page = min(per_page, MAX_PER_PAGE)

        self._validate_sort_params(sort_by, sort_order)

        offset = (page - 1) * per_page
        results, total_count = await self._repository.browse_books(
            offset=offset, limit=per_page,
            sort_by=sort_by, sort_order=sort_order,
        )

        items = self._to_summary(results)

        return BookListResponse(items=items, page=page, per_page=per_page, total=total_count)

    async def get_book_details(self, biblio_id) -> BookDetailSchema:
        book = await self._repository.get_book_by_id(biblio_id)
        if book is None:
            raise BookNotFoundError(biblio_id)

        return BookDetailSchema.model_validate(book)

    def _to_summary(self, result):
        return [BookSummarySchema.model_validate(r) for r in result]

    def _validate_sort_params(self, sort_by, sort_order):
        if sort_by not in ALLOWED_SORT_FIELDS:
            raise ServiceValidationError(
                f"sort_by must be one of: {', '.join(sorted(ALLOWED_SORT_FIELDS))}"
            )
        if sort_order not in {"asc", "desc"}:
            raise ServiceValidationError("sort_order must be 'asc' or 'desc'")
            
    


    async def check_availability(self, biblio_id) -> BookAvailabilitySchema:
        items = await self._koha_client.get_availability(biblio_id)

        if items is None:
            raise BiblioNotFoundError(biblio_id)

        total_copies = len(items)
        available_copies = sum(1 for item in items if _is_item_available(item))

        await self._sync_db_copies(biblio_id, items)

        return BookAvailabilitySchema(
            biblio_id=biblio_id,
            available=available_copies > 0,
            available_copies=available_copies,
            total_copies=total_copies,
        )

    async def _sync_db_copies(self, biblio_id: int, koha_items: list[dict]) -> None:
        db = self._repository.db
        now = datetime.now(timezone.utc)

        db_copies = await self._repository.get_copies_by_biblio_id(biblio_id)
        db_copy_map = {c.item_id: c for c in db_copies}

        koha_item_ids: set[int] = set()

        for item in koha_items:
            item_id = item.get("item_id")
            item_biblio_id = item.get("biblio_id")
            if item_id is None or item_biblio_id is None:
                continue

            koha_item_ids.add(item_id)
            branch = item.get("home_library_id")
            callnumber = item.get("callnumber")
            status = "Available" if _is_item_available(item) else "Not Available"

            db_copy = db_copy_map.get(item_id)
            if (
                db_copy is not None
                and db_copy.branch == branch
                and db_copy.callnumber == callnumber
                and db_copy.status == status
            ):
                continue

            book_stmt = insert(Book).values(biblio_id=biblio_id, title="Unknown Title")
            book_stmt = book_stmt.on_conflict_do_nothing()
            await db.execute(book_stmt)

            copy_stmt = insert(BookCopy).values(
                item_id=item_id,
                biblio_id=biblio_id,
                branch=branch,
                callnumber=callnumber,
                acquisition_date=_parse_koha_date(item.get("acquisition_date")),
                status=status,
                last_seen_at=now,
            )
            copy_stmt = copy_stmt.on_conflict_do_update(
                index_elements=[BookCopy.item_id],
                set_={
                    "branch": copy_stmt.excluded.branch,
                    "callnumber": copy_stmt.excluded.callnumber,
                    "acquisition_date": copy_stmt.excluded.acquisition_date,
                    "status": copy_stmt.excluded.status,
                    "last_seen_at": now,
                },
            )
            await db.execute(copy_stmt)

        for db_copy in db_copies:
            if db_copy.item_id not in koha_item_ids:
                await db.execute(
                    delete(BookCopy).where(BookCopy.item_id == db_copy.item_id)
                )

        await db.execute(
            update(Book)
            .where(Book.biblio_id == biblio_id)
            .values(availability_synced_at=now)
        )

        await db.commit()
