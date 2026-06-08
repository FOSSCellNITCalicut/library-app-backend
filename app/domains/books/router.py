from fastapi import APIRouter, Depends,HTTPException,Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.domains.books import service
from app.domains.books.schemas import (
    BrowseResponse,
    SearchResponse,
    BookDetail,
    ErrorResponse,
)

router = APIRouter(prefix="/books", tags=["books"])

#Browse
# GET /api/v1/books/browse?page=1
@router.get(
    "/browse",
    response_model=BrowseResponse,
    summary="Browse books catalog",
    description="Returns paginated books ordered by newest additions. 50 books per page.",
)

async def browse_books(
    page: int = Query(default=1, ge=1, description="Page number, starts at 1"),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_browse_books(db, page=page)

#Search
# GET /api/v1/books/search?q=python
@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search books",
    description="Full-text search across title and authors.",
    responses={400: {"model": ErrorResponse, "description": "Empty query"}},
)
async def search_books(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    db: AsyncSession = Depends(get_db),
):
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Search query cannot be empty.")
    return await service.search_books(db, q=q)

#Book Detail
# GET /api/v1/books/{biblio_id}

@router.get(
    "/{biblio_id}",
    response_model=BookDetail,
    summary="Get book details",
    description="Returns full metadata and availability for a single book.",
    responses={
        404: {"model": ErrorResponse, "description": "Book not found"},
        400: {"model": ErrorResponse, "description": "Invalid biblio_id"},
    },
)

async def get_book(
    biblio_id: int,
    db: AsyncSession = Depends(get_db),
):
    if biblio_id <= 0:
        raise HTTPException(status_code=400, detail="biblio_id must be a positive integer.")

    book = await service.get_book_by_id(db, biblio_id=biblio_id)

    if book is None:
        raise HTTPException(
            status_code=404,
            detail=f"Book with biblio_id {biblio_id} not found.",
        )

    return book
