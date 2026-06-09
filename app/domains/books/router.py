from fastapi import APIRouter, Query,Path, Depends,HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.domains.books import service as service



router = APIRouter(prefix="/books", tags=["books"])

@router.get("/browse")
async def browse_books(
    page: int = Query(default=1, ge=1, description="Page number for pagination"),
    per_page: int = Query(default=20, ge=1, le=100, description="Number of books per page"),
    home_library_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),

):
    return await service.get_browse_books(
        db, 
        page=page,
        per_page=per_page,
        home_library_id=home_library_id
    )
     # return await service.get_browse_books(db, page=page)
@router.get("/search")
async def search_books(
    q: str = Query(..., min_length=1, max_length=100, description="Search query for books"),
    page: int = Query(default=1, ge=1, description="Page number for pagination"),
    db: AsyncSession = Depends(get_db),
):
    q = q.strip()
    if not q:
        raise HTTPException(
            status_code=400,
            detail="Search query cannot be empty"
        )
    return await service.search_books(db, q=q,page=page)


@router.get("/{biblio_id}")
async def get_book(
    biblio_id: int = Path(..., description="ID of the book to retrieve"),
    db: AsyncSession = Depends(get_db),
):
    book =  await service.get_book(db, biblio_id=biblio_id)

    if book is None:
        raise HTTPException(
            status_code=404,
            detail=f"Book with ID {biblio_id} not found"
        )
    return book


