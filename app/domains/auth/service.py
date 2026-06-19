import asyncio
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, TypeVar

import httpx
import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.auth.account_parser import AccountPageData, parse_account_page, parse_charges_page
from app.domains.auth.crypto import CredsEncryptionUnavailable, decrypt_password, encrypt_password
from app.domains.auth.models import User

logger = logging.getLogger(__name__)

_KOHA_LOGIN_URL = f"{settings.KOHA_OPAC_URL}/cgi-bin/koha/opac-user.pl"


# ---------------------------------------------------------------------------
# Koha OPAC authentication
# ---------------------------------------------------------------------------

class KohaAuthError(Exception):
    """Raised when Koha rejects credentials. Never retried -- retrying a
    wrong password just hammers Koha for no benefit."""


class KohaSessionExpired(Exception):
    """
    Raised by Koha-authenticated calls (future user-domain endpoints: checkouts,
    renew, holds, fines) when the stored CGISESSID is no longer valid -- e.g.
    Koha returned its login page instead of the expected data.

    call_with_koha_retry() catches this, re-authenticates using stored
    "remember me" credentials if available, and retries once.
    """


async def _koha_login(roll_no: str, password: str) -> tuple[str, AccountPageData]:
    """
    POST credentials to Koha's OPAC login form.

    Koha returns HTTP 302 on success (redirect to account page) and HTTP 200
    on failure (renders the login form again). This is a web-app convention,
    not a REST convention.

    Retries up to MAX_KOHA_LOGIN_RETRIES times on transient failures only:
    connection errors, timeouts, and 5xx responses. A 200 (wrong credentials)
    is a definitive answer and is never retried.

    Returns (cgisessid, AccountPageData).
    Raises KohaAuthError on invalid credentials.
    Raises HTTPException(502) if Koha is unreachable after all retries.
    """
    last_error: Exception | None = None

    for attempt in range(1, settings.MAX_KOHA_LOGIN_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=settings.KOHA_LOGIN_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    _KOHA_LOGIN_URL,
                    data={
                        "userid": roll_no,
                        "password": password,
                        "koha_login_context": "opac",
                    },
                )

            if response.status_code == 200:
                raise KohaAuthError("Invalid credentials")

            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Koha server error: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            cgisessid = response.cookies.get("CGISESSID")
            if not cgisessid:
                logger.error(
                    "Koha login for %s returned %s but no CGISESSID cookie",
                    roll_no, response.status_code,
                )
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Koha session error")

            async with httpx.AsyncClient(timeout=10) as client:
                account_response = await client.get(
                    _KOHA_LOGIN_URL,
                    cookies={"CGISESSID": cgisessid},
                )
            if "koha_login_context" in account_response.text:
                raise KohaSessionExpired()
            account_data = parse_account_page(account_response.text, roll_no)
            return cgisessid, account_data

        except KohaAuthError:
            raise
        except HTTPException:
            raise  # CGISESSID missing is not transient
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_error = exc
            logger.warning(
                "Koha login attempt %d/%d for %s failed: %s",
                attempt, settings.MAX_KOHA_LOGIN_RETRIES, roll_no, exc,
            )
            if attempt < settings.MAX_KOHA_LOGIN_RETRIES:
                await asyncio.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s...
                continue
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Koha is unreachable") from exc

    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Koha is unreachable") from last_error


async def fetch_and_parse_account_page(cgisessid: str, roll_no: str) -> AccountPageData:
    """
    GET the authenticated Koha OPAC user page and parse all user data.
    Returns AccountPageData with name, email, checkouts, fines, etc.

    Raises KohaSessionExpired when Koha returns the login page instead of
    account data (stale CGISESSID). call_with_koha_retry() catches this and
    transparently re-authenticates before retrying.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                _KOHA_LOGIN_URL,
                cookies={"CGISESSID": cgisessid},
            )
        if "koha_login_context" in response.text:
            raise KohaSessionExpired()
        return parse_account_page(response.text, roll_no)
    except KohaSessionExpired:
        raise
    except Exception:
        logger.warning(
            "Could not fetch or parse account page from Koha for roll_no=%s",
            roll_no, exc_info=True,
        )
        return AccountPageData(name=roll_no)


async def fetch_and_parse_charges_page(cgisessid: str, roll_no: str) -> AccountPageData:
    """
    GET the authenticated Koha OPAC charges page (opac-account.pl)
    and parse fine/charge data.
    Returns AccountPageData with outstanding_fine and fine_history populated.

    Raises KohaSessionExpired when Koha returns the login page instead of
    account data (stale CGISESSID). call_with_koha_retry() catches this and
    transparently re-authenticates before retrying.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                _KOHA_CHARGES_URL,
                cookies={"CGISESSID": cgisessid},
            )
        if "koha_login_context" in response.text:
            raise KohaSessionExpired()
        return parse_charges_page(response.text, roll_no)
    except KohaSessionExpired:
        raise
    except Exception:
        logger.warning(
            "Could not fetch or parse charges page from Koha for roll_no=%s",
            roll_no, exc_info=True,
        )
        return AccountPageData(name=roll_no, outstanding_fine=0.0, fine_history=[])


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
    claims and compare SHA-256 hashes.

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
# Token hash helpers
# ---------------------------------------------------------------------------

def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _verify_token_hash(raw_token: str, stored_hash: str) -> bool:
    return hashlib.sha256(raw_token.encode()).hexdigest() == stored_hash


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
        cgisessid, account = await _koha_login(roll_no, password)
    except KohaAuthError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid roll number or password")

    name = account.name
    email = account.email

    jti = secrets.token_urlsafe(32)
    access_token = create_access_token(roll_no, name)
    refresh_token = create_refresh_token(roll_no, jti)

    refresh_hash = _hash_token(jti)

    creds_enc = None
    if remember_me:
        try:
            creds_enc = encrypt_password(password)
        except CredsEncryptionUnavailable:
            # Server isn't configured for remember-me (CREDS_ENCRYPTION_KEY unset).
            # Don't fail the whole login over an optional feature -- just skip it.
            logger.warning(
                "remember_me requested for %s but CREDS_ENCRYPTION_KEY is not configured -- skipping",
                roll_no,
            )

    # Merge = INSERT or UPDATE. One row per user; a new login overwrites the old session.
    user = User(
        roll_no=roll_no,
        cgisessid=cgisessid,
        name=name,
        email=email,
        refresh_token_hash=refresh_hash,
        creds_enc=creds_enc,
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


_KOHA_CHARGES_URL = f"{settings.KOHA_OPAC_URL}/cgi-bin/koha/opac-account.pl"

_KOHA_LOGOUT_URL = f"{settings.KOHA_OPAC_URL}/cgi-bin/koha/opac-main.pl?logout.x=1"


async def _koha_logout(cgisessid: str) -> None:
    """Invalidate the CGISESSID on Koha's side."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(
                _KOHA_LOGOUT_URL,
                cookies={"CGISESSID": cgisessid},
            )
    except Exception:
        logger.warning("Failed to call Koha logout endpoint", exc_info=True)


async def logout(roll_no: str, db: AsyncSession) -> None:
    """Delete the user's session, invalidating all tokens immediately."""
    result = await db.execute(select(User).where(User.roll_no == roll_no))
    user = result.scalar_one_or_none()
    if user:
        await _koha_logout(user.cgisessid)
        await db.delete(user)
        await db.commit()


# ---------------------------------------------------------------------------
# Remember-me: transparent re-authentication on stale Koha session
# ---------------------------------------------------------------------------

async def reauthenticate(user: User, db: AsyncSession) -> str:
    """
    Re-login to Koha using the user's stored encrypted credentials, used when
    their CGISESSID has gone stale. Updates the stored cgisessid + name + email.

    Raises HTTPException(401) if the user never enabled remember-me (no
    creds_enc) -- the caller should surface this as "please log in again".
    """
    if user.creds_enc is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired, please log in again")

    password = decrypt_password(user.creds_enc)

    try:
        cgisessid, account = await _koha_login(user.roll_no, password)
    except KohaAuthError as exc:
        # Stored credentials no longer work (e.g. password changed on Koha's side).
        # Drop them so we don't keep retrying a doomed re-auth.
        user.creds_enc = None
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired, please log in again") from exc

    user.cgisessid = cgisessid
    user.name = account.name
    user.email = account.email
    await db.commit()
    return cgisessid


_T = TypeVar("_T")


async def call_with_koha_retry(roll_no: str, db: AsyncSession, koha_call: Callable[[str], Awaitable[_T]]) -> _T:
    """
    Run a Koha-authenticated call, transparently re-authenticating once if it
    signals a stale session.

    `koha_call` receives the current cgisessid and should raise
    KohaSessionExpired if Koha's response indicates the session is no longer
    valid (e.g. it served the login page instead of the expected data).

    Usage (future user-domain endpoints):
        async def _fetch_checkouts(cgisessid: str) -> list[Checkout]:
            response = await client.get(..., cookies={"CGISESSID": cgisessid})
            if "login" in response.url.path:
                raise KohaSessionExpired()
            return parse(response)

        checkouts = await call_with_koha_retry(roll_no, db, _fetch_checkouts)
    """
    result = await db.execute(select(User).where(User.roll_no == roll_no))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found")

    try:
        return await koha_call(user.cgisessid)
    except KohaSessionExpired:
        new_cgisessid = await reauthenticate(user, db)
        return await koha_call(new_cgisessid)
