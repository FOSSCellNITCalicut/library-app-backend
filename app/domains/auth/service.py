import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
import jwt
from bs4 import BeautifulSoup
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.auth.models import User

logger = logging.getLogger(__name__)

_KOHA_LOGIN_URL = f"{settings.KOHA_OPAC_URL}/cgi-bin/koha/opac-user.pl"


# ---------------------------------------------------------------------------
# Koha OPAC authentication
# ---------------------------------------------------------------------------

class KohaAuthError(Exception):
    """Raised when Koha rejects credentials."""


async def _koha_login(roll_no: str, password: str) -> tuple[str, str]:
    """
    POST credentials to Koha's OPAC login form.

    Koha returns HTTP 302 on success (redirect to account page) and HTTP 200
    on failure (renders the login form again). This is a web-app convention,
    not a REST convention.

    Returns (cgisessid, display_name).
    Raises KohaAuthError on invalid credentials.
    Raises httpx.HTTPError on network/server failures.
    """
    async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
        response = await client.post(
            _KOHA_LOGIN_URL,
            data={
                "userid": roll_no,
                "password": password,
                "koha_login_context": "opac",
            },
        )

    if response.status_code == 200:
        # Koha returned the login page -- credentials are wrong.
        raise KohaAuthError("Invalid credentials")

    cgisessid = response.cookies.get("CGISESSID")
    if not cgisessid:
        # Redirect happened but no session cookie -- unexpected Koha state.
        logger.error(
            "Koha login for %s returned %s but no CGISESSID cookie",
            roll_no,
            response.status_code,
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Koha session error")

    name = await _fetch_koha_display_name(cgisessid, roll_no)
    return cgisessid, name


async def _fetch_koha_display_name(cgisessid: str, fallback: str) -> str:
    """
    GET the Koha OPAC user page and scrape the display name from the HTML.
    Falls back to the roll number if the name cannot be found.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                _KOHA_LOGIN_URL,
                cookies={"CGISESSID": cgisessid},
            )
        soup = BeautifulSoup(response.text, "lxml")

        # Koha OPAC stores the logged-in name in one of these elements.
        for selector in [
            {"id": "logged-in-info-full"},
            {"class": "loggedinusername"},
            {"id": "logged-in-name"},
        ]:
            tag = soup.find(attrs=selector)
            if tag and tag.get_text(strip=True):
                return tag.get_text(strip=True)

    except Exception:
        logger.warning("Could not fetch display name from Koha for %s", fallback, exc_info=True)

    return fallback


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(roll_no: str, name: str) -> str:
    payload = {
        "sub": roll_no,
        "name": name,
        "role": "student",
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(roll_no: str, jti: str) -> str:
    """
    The `jti` (JWT ID) is a random token we generate, embed in the JWT, and hash
    for storage. On the next /auth/refresh call we extract `jti` from the decoded
    claims and bcrypt.checkpw it against the stored hash.

    This means the thing we're verifying is: did this specific device produce the
    token we last issued? The JWT signature already protects the jti from tampering.
    """
    payload = {
        "sub": roll_no,
        "type": "refresh",
        "jti": jti,
        "iat": _now(),
        "exp": _now() + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT signature and expiry.
    Raises HTTPException 401 on any failure.

    We explicitly pass algorithms= to prevent algorithm confusion attacks
    (an attacker swapping "HS256" to "none" in the header).
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ---------------------------------------------------------------------------
# bcrypt helpers
# ---------------------------------------------------------------------------

def _hash_token(raw_token: str) -> str:
    return bcrypt.hashpw(raw_token.encode(), bcrypt.gensalt()).decode()


def _verify_token_hash(raw_token: str, stored_hash: str) -> bool:
    return bcrypt.checkpw(raw_token.encode(), stored_hash.encode())


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

async def login(roll_no: str, password: str, remember_me: bool, db: AsyncSession) -> tuple[str, str, str]:
    """
    Full login flow.

    1. Authenticate with Koha.
    2. Generate access + refresh tokens.
    3. Upsert the session into the DB (one active session per user).

    Returns (access_token, refresh_token, display_name).
    """
    try:
        cgisessid, name = await _koha_login(roll_no, password)
    except KohaAuthError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid roll number or password")

    jti = secrets.token_urlsafe(32)
    access_token = create_access_token(roll_no, name)
    refresh_token = create_refresh_token(roll_no, jti)

    refresh_hash = _hash_token(jti)

    # Merge = INSERT or UPDATE. One row per user; a new login overwrites the old session.
    user = User(
        roll_no=roll_no,
        cgisessid=cgisessid,
        name=name,
        refresh_token_hash=refresh_hash,
        creds_enc=None,  # remember_me encryption is a follow-up task
    )
    await db.merge(user)
    await db.commit()

    # The raw refresh token (not the hash) is what the client must store and send back.
    # We embed it inside the signed JWT so the client only handles one string.
    return access_token, refresh_token, name


async def refresh(refresh_token_str: str, db: AsyncSession) -> tuple[str, str]:
    """
    Token rotation.

    1. Validate JWT signature + expiry.
    2. Verify the token is the one currently on record (hash comparison).
    3. If a revoked token is submitted, invalidate the entire session (reuse detection).
    4. Issue new access + refresh tokens atomically.

    Returns (new_access_token, new_refresh_token).
    """
    claims = decode_token(refresh_token_str)
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    roll_no = claims["sub"]

    # Lock the row to make token rotation atomic under concurrent requests.
    result = await db.execute(
        select(User).where(User.roll_no == roll_no).with_for_update()
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found")

    jti = claims.get("jti")
    if not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    if not _verify_token_hash(jti, user.refresh_token_hash):
        # Revoked token was submitted -- session is likely compromised.
        logger.warning("Refresh token reuse detected for roll_no=%s -- invalidating session", roll_no)
        await db.delete(user)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token already used")

    new_jti = secrets.token_urlsafe(32)
    new_access_token = create_access_token(roll_no, user.name)
    new_refresh_token = create_refresh_token(roll_no, new_jti)

    user.refresh_token_hash = _hash_token(new_jti)
    await db.commit()

    return new_access_token, new_refresh_token


async def logout(roll_no: str, db: AsyncSession) -> None:
    """Delete the user's session, invalidating all tokens immediately."""
    result = await db.execute(select(User).where(User.roll_no == roll_no))
    user = result.scalar_one_or_none()
    if user:
        await db.delete(user)
        await db.commit()
