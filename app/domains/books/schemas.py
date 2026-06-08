from pydantic import BaseModel, Field
from typing import Optional

class BookBase(BaseModel):
    biblio_id: int
    title: str
    authors: list[str]
    edition: Optional[str] = None
    cover_url: Optional[str] = None
    available_copies: int
    total_copies: int
    lib_copies: int
    mat_copies: int

    model_config = {"from_attributes": True}

class BookCard(BaseModel):
    biblio_id: int
    title: str
    isbn: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    cover_url: Optional[str] = None

    model_config = {"from_attributes": True}

class BrowseResponse(BaseModel):
    items: list[BookCard]
    page: int
    page_size: int
    has_more: bool

class SearchResponse(BaseModel):
    items: list[BookCard]
    query: str
    total: int

class BookDetail(BaseModel):
    biblio_id: int
    title: str
    authors: list[str]
    isbn: list[str]
    publisher: Optional[str] = None
    published_year: Optional[int] = None
    edition: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    categories: list[str]
    available_copies: int
    total_copies: int
    lib_copies: int
    mat_copies: int

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    detail: str