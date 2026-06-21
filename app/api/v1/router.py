from fastapi import APIRouter

from app.domains.books.router import router as books_router
from app.domains.auth.router import router as auth_router
from app.domains.users.router import router as users_router


router = APIRouter(prefix="/api/v1")
router.include_router(books_router)
router.include_router(auth_router)
router.include_router(users_router)
