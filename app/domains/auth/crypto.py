import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

# GCM's standard nonce size. Reusing a nonce with the same key breaks AES-GCM's
# security guarantees, so a fresh random one is generated per encryption and
# stored alongside the ciphertext (it doesn't need to be secret, only unique).
_NONCE_SIZE = 12


class CredsEncryptionUnavailable(Exception):
    """Raised when CREDS_ENCRYPTION_KEY is not configured on this server."""


def _aesgcm() -> AESGCM:
    if not settings.CREDS_ENCRYPTION_KEY:
        raise CredsEncryptionUnavailable()
    key = bytes.fromhex(settings.CREDS_ENCRYPTION_KEY)
    return AESGCM(key)


def encrypt_password(password: str) -> bytes:
    """
    Encrypt a password for "remember me" storage.

    Only the password is encrypted -- roll_no is already the row's primary
    key, so storing it again inside the ciphertext would be redundant and
    would let a decrypted blob disagree with the row it's attached to.
    """
    aesgcm = _aesgcm()
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = aesgcm.encrypt(nonce, password.encode(), None)
    return nonce + ciphertext


def decrypt_password(blob: bytes) -> str:
    aesgcm = _aesgcm()
    nonce, ciphertext = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
