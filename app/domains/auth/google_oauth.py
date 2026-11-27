"""Google ID-token verification and NITC identity parsing."""

import re
import logging

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

_NITC_DOMAIN = "nitc.ac.in"
# NITC student IDs contain a category prefix (B/M/P), a batch/year and an
# alphanumeric programme/sequence. Requiring a digit avoids treating ordinary
# ``firstname_lastname`` faculty addresses as roll numbers.
_STUDENT_ID = re.compile(r"^[BMP][A-Z0-9]{4,15}$", re.IGNORECASE)


def extract_student_roll_no(email: str) -> str | None:
    """Return the roll number from ``name_rollno@nitc.ac.in``, if present."""
    local, separator, domain = email.strip().rpartition("@")
    if not separator or domain.casefold() != _NITC_DOMAIN:
        return None

    name, separator, candidate = local.rpartition("_")
    if not name or not separator or not candidate or not any(char.isdigit() for char in candidate):
        return None
    if not _STUDENT_ID.fullmatch(candidate):
        return None
    return candidate.upper()


def verify_google_id_token(token: str) -> dict:
    """Verify Google's signed ID token and require a verified NITC account."""
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this server",
        )

    try:
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google token verification is not available on this server",
        ) from exc

    try:
        claims = id_token.verify_oauth2_token(
            token,
            Request(),
            audience=settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        ) from exc
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google token verification is temporarily unavailable",
        ) from exc

    email = claims.get("email")
    email_domain_ok = isinstance(email, str) and email.casefold().endswith(f"@{_NITC_DOMAIN}")
    hosted_domain_ok = (
        isinstance(claims.get("hd"), str)
        and claims["hd"].casefold() == _NITC_DOMAIN
    )
    email_verified = claims.get("email_verified") is True
    subject_present = isinstance(claims.get("sub"), str) and bool(claims["sub"])
    if not (email_domain_ok and hosted_domain_ok and email_verified and subject_present):
        logger.warning(
            "Rejected Google ID claims: nitc_email=%s hosted_domain_matches=%s "
            "email_verified=%s subject_present=%s",
            email_domain_ok,
            hosted_domain_ok,
            email_verified,
            subject_present,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Use a verified NITC Google account",
        )

    claims["email"] = email.strip().lower()
    return claims
