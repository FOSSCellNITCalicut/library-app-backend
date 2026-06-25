from pydantic import BaseModel, Field


class QuoteSchema(BaseModel):
    text: str = Field(description="Quote text")
    source: str | None = Field(default=None, description="Quote attribution/source")


class BusinessHourEntry(BaseModel):
    area: str = Field(description="Library area name (e.g. Stack 1)")
    schedule: str = Field(description="Operating hours string")


class BookArrangementEntry(BaseModel):
    stack: str = Field(description="Stack identifier (e.g. Stack 1)")
    call_range: str = Field(description="Dewey call number range (e.g. 000-599)")


class NewArrivalSchema(BaseModel):
    biblio_id: int = Field(description="Koha bibliographic record ID")
    title: str
    cover_url: str | None = Field(default=None, description="Book cover image URL")
    authors: list[str] = Field(default_factory=list)


class OpacHomeResponse(BaseModel):
    quote: QuoteSchema | None = Field(default=None, description="Quote of the day")
    business_hours: list[BusinessHourEntry] = Field(default_factory=list)
    book_arrangement: list[BookArrangementEntry] = Field(default_factory=list)
    new_arrivals: list[NewArrivalSchema] = Field(default_factory=list)
