import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.models.user_api_key import UserApiKey

router = APIRouter(prefix="/users/me/api-keys", tags=["api-keys"])

_PREFIX = "nxr_"
_MAX_KEYS = 20


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyResponse):
    key: str


class CreateApiKeyRequest(BaseModel):
    name: str


@router.get("/", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("/", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(
    req: CreateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count_result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id)
    )
    if len(count_result.scalars().all()) >= _MAX_KEYS:
        raise HTTPException(status_code=400, detail=f"Maximum {_MAX_KEYS} API keys allowed")

    raw_key = _PREFIX + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = UserApiKey(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=req.name.strip() or "API Key",
        key_hash=key_hash,
        prefix=raw_key[:12],
        created_at=datetime.now(timezone.utc),
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return {**ApiKeyResponse.model_validate(api_key).model_dump(), "key": raw_key}


@router.post("/{key_id}/rotate", response_model=ApiKeyCreateResponse)
async def rotate_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.id == key_id, UserApiKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    raw_key = _PREFIX + secrets.token_hex(32)
    api_key.key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key.prefix = raw_key[:12]
    api_key.last_used_at = None
    await db.commit()
    await db.refresh(api_key)
    return {**ApiKeyResponse.model_validate(api_key).model_dump(), "key": raw_key}


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.id == key_id, UserApiKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(api_key)
    await db.commit()
