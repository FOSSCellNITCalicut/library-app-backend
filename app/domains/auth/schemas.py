from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    roll_no: str = Field(..., examples=["B23CS001"])
    password: str = Field(..., min_length=1)
    remember_me: bool = False


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(..., min_length=1)
    emp_id: str | None = None
    password: str | None = None
    remember_me: bool = False


class UserInfo(BaseModel):
    roll_no: str
    name: str
    user_type: str = "student"
    emp_id: str | None = None
    is_google_verified: bool = False


class LoginResponse(BaseModel):
    success: bool = True
    user: UserInfo
    access_token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str


class LogoutResponse(BaseModel):
    success: bool = True


class TokenClaims(BaseModel):
    """Decoded JWT claims attached to the request by the auth middleware."""
    sub: str       # roll_no
    name: str
    role: str
    type: str      # "access" or "refresh"
