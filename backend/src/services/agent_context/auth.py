"""WebSocket authentication helper."""
import hashlib
from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import WebSocket
from src.core.database import AsyncSessionLocal
from src.core.security import decode_token
from src.models.user import User


async def authenticate_ws(websocket: WebSocket) -> User | None:
    token = websocket.query_params.get("token")
    if not token:
        return None

    if token.startswith("nxr_"):
        from src.models.user_api_key import UserApiKey
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(UserApiKey).where(UserApiKey.key_hash == key_hash))
            api_key = result.scalar_one_or_none()
            if not api_key:
                return None
            result = await db.execute(select(User).where(User.id == api_key.user_id))
            user = result.scalar_one_or_none()
            if not user or not user.is_active:
                return None
            api_key.last_used_at = datetime.now(timezone.utc)
            await db.commit()
            return user

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
    except Exception:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
