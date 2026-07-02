from fastapi import APIRouter, Path,Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.domains.books.service import BookService
from app.domains.books.repository import BooksRepository
from app.domains.catalog.service import CatalogService
from app.domains.catalog.schemas import CatalogBooksResponse

router = APIRouter(prefix="/catalog",tags=["catalog"])

def get_catalog_service(db: AsyncSession = Depends(get_db)) -> CatalogService:
    book_service = BookService(BooksRepository(db))
    return CatalogService(db, book_service)

@router.get(
    "/{course_id}",
    response_model=CatalogBooksResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Books for course retrieved successfully"},
        500: {"description": "Internal server error"},
    },
)

async def get_course_books(
    service: CatalogService = Depends(get_catalog_service),
    course_id: str = Path(..., description="The ID of the course"),
):
    return await service.get_books_for_course(course_id)

