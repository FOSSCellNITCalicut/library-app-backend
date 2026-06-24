from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, computed_field

# Coerces NULL from the DB into an empty list so the frontend never gets null.
StringList = Annotated[list[str], BeforeValidator(lambda v: v if v is not None else [])]


class BookCopySchema(BaseModel):
    """One physical copy of a book held by the library."""

    model_config = ConfigDict(from_attributes=True)

    item_id: int = Field(description="Unique ID of this physical copy")
    branch: str = Field(description="Branch that owns this copy (LIB or MAT)")
    callnumber: str | None = Field(default=None, description="Shelf location code")
    status: str = Field(description="Current circulation status of this copy")
    acquisition_date: date | None = Field(
        default=None, description="Date the library acquired this copy"
    )


class BookSummarySchema(BaseModel):
    """Compact book card used in search results and browse lists."""

    model_config = ConfigDict(from_attributes=True)

    biblio_id: int = Field(description="Koha bibliographic record ID")
    title: str
    authors: StringList = Field(default_factory=list)
    isbn: StringList = Field(default_factory=list, description="One or more ISBNs")
    edition: str | None = None
    cover_url: str | None = None
    available_copies: int = Field(
        description="Number of copies available to borrow right now"
    )
    total_copies: int = Field(description="Total physical copies across all branches")

    # Used only to derive `branches`; excluded from the serialized output.
    lib_copies: int = Field(exclude=True)
    mat_copies: int = Field(exclude=True)

    @computed_field(description="Branches that hold at least one copy of this book")
    @property
    def branches(self) -> list[str]:
        result = []
        if self.lib_copies > 0:
            result.append("LIB")
        if self.mat_copies > 0:
            result.append("MAT")
        return result


class BookDetailSchema(BaseModel):
    """Full book record returned by GET /api/v1/books/{biblio_id}."""

    model_config = ConfigDict(from_attributes=True)

    biblio_id: int = Field(description="Koha bibliographic record ID")
    title: str
    authors: StringList = Field(default_factory=list)
    isbn: StringList = Field(default_factory=list, description="One or more ISBNs (older books may have none)")
    publisher: str | None = None
    published_year: int | None = None
    edition: str | None = None
    description: str | None = None
    cover_url: str | None = None
    categories: StringList = Field(default_factory=list)

    # Availability aggregates kept at the book level by DB triggers
    total_copies: int
    available_copies: int
    lib_copies: int = Field(description="Copies held by the Main Library (LIB)")
    mat_copies: int = Field(description="Copies held by the Maths Dept Library (MAT)")

    # Lets the Flutter app decide whether to offer a live-refresh button
    # (architecture: refresh if now() - availability_synced_at > 120 s)
    availability_synced_at: datetime | None = None

    copies: list[BookCopySchema] | None = Field(
        default=None,
        description="Individual physical copies; included only when explicitly requested",
    )


class BookListResponse(BaseModel):
    """Paginated list of books returned by search and browse endpoints."""

    items: list[BookSummarySchema]
    page: int = Field(ge=1)
    per_page: int = Field(ge=1)
    total: int = Field(ge=0, description="Total number of matching books")

    @computed_field
    @property
    def has_more(self) -> bool:
        return self.page * self.per_page < self.total
        
        
class BookAvailabilitySchema(BaseModel):
    """Live availability check, fetched directly from Koha (not the DB cache)."""

    biblio_id: int
    available: bool = Field(description="True if at least one copy can currently be borrowed")
    available_copies: int = Field(description="Number of copies currently available to borrow")
    total_copies: int = Field(description="Total physical copies returned by Koha for this biblio_id")
