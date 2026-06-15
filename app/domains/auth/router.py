from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.domains.auth import service
from app.domains.auth.schemas import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RefreshRequest,
    RefreshResponse,
    UserInfo,
)
from app.domains.auth.dependencies import get_current_user

router = APIRouter(tags=["auth"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: DB):
    access_token, refresh_token, name = await service.login(
        roll_no=body.roll_no,
        password=body.password,
        remember_me=body.remember_me,
        db=db,
    )
    return LoginResponse(
        user=UserInfo(roll_no=body.roll_no, name=name),
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/auth/refresh", response_model=RefreshResponse)
async def refresh(body: RefreshRequest, db: DB):
    access_token, refresh_token = await service.refresh(
        refresh_token_str=body.refresh_token,
        db=db,
    )
    return RefreshResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/auth/logout", response_model=LogoutResponse)
async def logout(claims: Annotated[dict, Depends(get_current_user)], db: DB):
    await service.logout(roll_no=claims["sub"], db=db)
    return LogoutResponse()
