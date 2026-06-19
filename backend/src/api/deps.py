import hashlib
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
from src.core.database import get_db
from src.core.security import decode_token
from src.models.user import User
from src.models.org import OrgMember

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
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
        api_key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        return user

    # JWT auth
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def require_superuser(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that gates an endpoint to superusers only."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser required")
    return current_user


async def get_active_org_id(user: User, db: AsyncSession) -> str:
    if user.active_org_id:
        result = await db.execute(
            select(OrgMember).where(
                OrgMember.user_id == user.id,
                OrgMember.org_id == user.active_org_id,
            )
        )
        if result.scalar_one_or_none():
            return user.active_org_id
    result = await db.execute(
        select(OrgMember).where(OrgMember.user_id == user.id).limit(1)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=404,
            detail="No organization found. Please create or join an organization."
        )
    return member.org_id
