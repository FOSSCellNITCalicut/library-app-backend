from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.domains.auth.dependencies import get_current_user
from app.domains.users import service
from app.domains.users.schemas import (
    BookStatusResponse,
    FineHistoryResponse,
    FinesResponse,
    UserMeResponse,
)

router = APIRouter(prefix="/user", tags=["user"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/me", response_model=UserMeResponse)
async def user_me(claims: Annotated[dict, Depends(get_current_user)], db: DB):
    return await service.get_user_profile(roll_no=claims["sub"], db=db)


@router.get("/fines", response_model=FinesResponse)
async def user_fines(claims: Annotated[dict, Depends(get_current_user)], db: DB):
    return await service.get_fines(roll_no=claims["sub"], db=db)


@router.get("/fines/history", response_model=FineHistoryResponse)
async def user_fines_history(claims: Annotated[dict, Depends(get_current_user)], db: DB):
    return await service.get_fines_history(roll_no=claims["sub"], db=db)


@router.get("/book-status/{biblio_id}", response_model=BookStatusResponse)
async def user_book_status(
    biblio_id: int,
    claims: Annotated[dict, Depends(get_current_user)],
    db: DB,
):
    return await service.get_book_status(
        roll_no=claims["sub"], biblio_id=biblio_id, db=db
    )
