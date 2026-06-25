import hashlib
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
from src.core.database import get_db
from src.core.security import decode_token
from src.models.user import User
from src.models.org import OrgMember

bearer = HTTPBearer(auto_error=False)

# HTTP methods that mutate state require the "write" scope; the rest need "read".
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = credentials.credentials

    # API key auth (nxr_ prefix)
    if token.startswith("nxr_"):
        from src.models.user_api_key import UserApiKey
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        result = await db.execute(select(UserApiKey).where(UserApiKey.key_hash == key_hash))
        api_key = result.scalar_one_or_none()
        if not api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        result = await db.execute(select(User).where(User.id == api_key.user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        # #177: enforce capability scope. An empty/absent scope list = full access
        # (keys minted before scoping). A scoped key rejects methods it lacks.
        scopes = api_key.scopes or []
        if scopes:
            needed = "write" if request.method.upper() in _WRITE_METHODS else "read"
            if needed not in scopes:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                    detail=f"API key lacks '{needed}' scope")
        # #177: stash any org restriction so get_active_org_id can enforce it.
        user._api_key_allowed_org_ids = api_key.allowed_org_ids or None  # type: ignore[attr-defined]
        api_key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        return user

    # JWT auth
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        # A 2FA-pending token (issued before TOTP is completed) must NOT grant access
        # to any real endpoint — only /totp-login accepts it (#161).
        if payload.get("scope") == "2fa_pending":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA not completed")
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # If the access token carries a token_version, it must match the user's current
    # one — a password change / logout-all bumps it and invalidates old tokens (#173).
    _tv = payload.get("tv")
    if _tv is not None and _tv != (user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return user


async def require_superuser(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that gates an endpoint to superusers only."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser required")
    return current_user


async def get_active_org_id(user: User, db: AsyncSession) -> str:
    # #177: when authenticated with an org-restricted API key, the resolved org
    # must be in the key's allowlist.
    allowed = getattr(user, "_api_key_allowed_org_ids", None)

    def _check(org_id: str) -> str:
        if allowed and org_id not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="API key is not authorized for this organization")
        return org_id

    if user.active_org_id:
        result = await db.execute(
            select(OrgMember).where(
                OrgMember.user_id == user.id,
                OrgMember.org_id == user.active_org_id,
            )
        )
        if result.scalar_one_or_none():
            return _check(user.active_org_id)
    # Fall back to the first membership — preferring one in the key's allowlist.
    result = await db.execute(
        select(OrgMember).where(OrgMember.user_id == user.id)
    )
    members = result.scalars().all()
    if not members:
        raise HTTPException(
            status_code=404,
            detail="No organization found. Please create or join an organization."
        )
    if allowed:
        for m in members:
            if m.org_id in allowed:
                return m.org_id
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="API key is not authorized for any of your organizations")
    return members[0].org_id
