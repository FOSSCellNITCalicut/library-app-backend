from fastapi import APIRouter
from app.domains.books.router import router as books_router


router = APIRouter(prefix="/api/v1")
router.include_router(books_router)

