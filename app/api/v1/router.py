from fastapi import APIRouter

from app.domains.books.router import router as books_router
from app.domains.auth.router import router as auth_router
from app.domains.users.router import router as users_router
from app.domains.opac_home.router import router as opac_home_router
from app.domains.curriculum.router import router as curriculum_router


router = APIRouter(prefix="/api/v1")
router.include_router(books_router)
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(opac_home_router)
router.include_router(curriculum_router)
