from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.domains.auth.service import decode_token

_bearer = HTTPBearer()


def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)]) -> dict:
    """
    FastAPI dependency for protected routes.

    Reads the `Authorization: Bearer <token>` header, validates the JWT
    signature and expiry, and returns the decoded claims dict.

    Usage in a route handler:
        @router.get("/user/checkouts")
        async def checkouts(claims: Annotated[dict, Depends(get_current_user)]):
            roll_no = claims["sub"]
    """
    claims = decode_token(credentials.credentials)
    if claims.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an access token")
    return claims
