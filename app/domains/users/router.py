from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.domains.auth.dependencies import get_current_user
from app.domains.users import service
from app.domains.users.schemas import (
    AccountActivityResponse,
    BookStatusResponse,
    CancelHoldResponse,
    FineHistoryResponse,
    FinesResponse,
    HoldFormResponse,
    HoldsResponse,
    PlaceHoldRequest,
    PlaceHoldResponse,
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


@router.get("/account/activity", response_model=AccountActivityResponse)
async def user_account_activity(claims: Annotated[dict, Depends(get_current_user)], db: DB):
    return await service.get_account_activity(roll_no=claims["sub"], db=db)


@router.get("/book-status/{biblio_id}", response_model=BookStatusResponse)
async def user_book_status(
    biblio_id: int,
    claims: Annotated[dict, Depends(get_current_user)],
    db: DB,
):
    return await service.get_book_status(
        roll_no=claims["sub"], biblio_id=biblio_id, db=db
    )


@router.get("/holds", response_model=HoldsResponse)
async def user_holds(claims: Annotated[dict, Depends(get_current_user)], db: DB):
    return await service.get_holds(roll_no=claims["sub"], db=db)


@router.post("/holds/{reserve_id}/cancel", response_model=CancelHoldResponse)
async def user_cancel_hold(
    reserve_id: str,
    claims: Annotated[dict, Depends(get_current_user)],
    db: DB,
):
    return await service.cancel_hold(roll_no=claims["sub"], reserve_id=reserve_id, db=db)


@router.get("/holds/{biblio_id}/form", response_model=HoldFormResponse)
async def user_hold_form(
    biblio_id: int,
    claims: Annotated[dict, Depends(get_current_user)],
    db: DB,
):
    return await service.get_hold_form(roll_no=claims["sub"], biblio_id=biblio_id, db=db)


@router.post("/holds/{biblio_id}", response_model=PlaceHoldResponse)
async def user_place_hold(
    biblio_id: int,
    body: PlaceHoldRequest,
    claims: Annotated[dict, Depends(get_current_user)],
    db: DB,
):
    return await service.place_hold(
        roll_no=claims["sub"], biblio_id=biblio_id, branch_code=body.branch_code, db=db
    )
