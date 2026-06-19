import logging
from datetime import datetime, timedelta, timezone
from typing import Any
import hashlib
from jose import jwt, JWTError
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
import secrets
from src.core.config import get_settings

logger = logging.getLogger(__name__)

_ph = PasswordHasher()

# Pre-computed hash used as a constant-time dummy when a user is not found,
# so login always runs verify_password and prevents timing-based email enumeration.
_DUMMY_HASH: str = _ph.hash("nexora-dummy-password-constant")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        logger.error("Unexpected error in verify_password", exc_info=True)
        return False


_fernet_instance: Fernet | None = None
_dev_key_warned = False


def _get_fernet() -> Fernet:
    global _fernet_instance, _dev_key_warned
    if _fernet_instance is not None:
        return _fernet_instance
    settings = get_settings()
    key = settings.encryption_key
    if not key:
        if settings.environment == "production":
            raise RuntimeError(
                "ENCRYPTION_KEY is not set. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        # Dev/test: auto-generate an ephemeral key so credentials are always encrypted.
        # Restarting the server invalidates all stored credentials — set ENCRYPTION_KEY to persist them.
        if not _dev_key_warned:
            logger.warning(
                "[security] ENCRYPTION_KEY not set — using an ephemeral dev key. "
                "Stored provider credentials will be unreadable after restart. "
                "Set ENCRYPTION_KEY in .env to persist them."
            )
            _dev_key_warned = True
        key = Fernet.generate_key().decode()
    try:
        _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet_instance
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"ENCRYPTION_KEY is invalid: {exc}") from exc


def create_token(data: dict[str, Any], expires_delta: timedelta) -> str:
    settings = get_settings()
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(user_id: str, org_id: str | None = None, expires_minutes: int | None = None, scope: str | None = None) -> str:
    settings = get_settings()
    payload: dict = {"sub": user_id, "org": org_id, "type": "access"}
    if scope:
        payload["scope"] = scope
    return create_token(payload, timedelta(minutes=expires_minutes or settings.access_token_expire_minutes))


def create_refresh_token(user_id: str, token_version: int = 1) -> str:
    settings = get_settings()
    return create_token(
        {"sub": user_id, "type": "refresh", "jti": secrets.token_urlsafe(16), "tv": token_version},
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
