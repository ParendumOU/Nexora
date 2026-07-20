import re
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator
from src.api.deps import get_current_user, get_db
from src.core.security import hash_password, verify_password
from src.models.user import User
from src.models.user_profile_fact import UserProfileFact

router = APIRouter(prefix="/users", tags=["users"])


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    avatar_url: str | None
    avatar_emoji: str | None
    telegram_user_id: str | None
    notes: str | None
    contact_info: str | None
    is_active: bool
    is_superuser: bool
    is_managed: bool = False
    has_password: bool = True
    notify_email: bool = False
    notify_telegram: bool = False
    # Per-member LLM-provider governance in the caller's active org (read-only here;
    # admins set it). provider_mode is all|own|assigned; assigned_provider_count is how
    # many accounts are reserved to this user. None mode = not a governed member row.
    provider_mode: str | None = None
    assigned_provider_count: int = 0

    model_config = {"from_attributes": True}


class UpdateUserRequest(BaseModel):
    # #167: cap unbounded text fields so a client can't store megabytes.
    full_name: str | None = Field(None, max_length=255)
    avatar_url: str | None = Field(None, max_length=2048)
    avatar_emoji: str | None = Field(None, max_length=16)
    notes: str | None = Field(None, max_length=20000)
    contact_info: str | None = Field(None, max_length=10000)
    # #212: notification delivery channel opt-ins.
    notify_email: bool | None = None
    notify_telegram: bool | None = None


class ChangePasswordRequest(BaseModel):
    # Optional: a passwordless (CLI-onboarded) account sets its first password without
    # one. An account that already has a password must supply the correct current one.
    current_password: str | None = None
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        errors = []
        if len(v) < 8:
            errors.append("at least 8 characters")
        if not re.search(r"[A-Z]", v):
            errors.append("one uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("one lowercase letter")
        if not re.search(r"\d", v):
            errors.append("one digit")
        if errors:
            raise ValueError("Password must contain: " + ", ".join(errors))
        return v


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resp = UserResponse.model_validate(current_user)
    # Surface the caller's own provider governance for the active org, so clients (CLI)
    # can reflect it read-only without listing the whole org membership.
    org_id = getattr(current_user, "active_org_id", None)
    if org_id:
        from sqlalchemy import func
        from src.models.org import OrgMember
        from src.models.provider import Provider

        mr = await db.execute(
            select(OrgMember.provider_mode).where(
                OrgMember.org_id == org_id, OrgMember.user_id == current_user.id
            )
        )
        mode = mr.scalar_one_or_none()
        if mode:
            resp.provider_mode = mode
        cr = await db.execute(
            select(func.count()).select_from(Provider).where(
                Provider.org_id == org_id, Provider.assigned_user_id == current_user.id
            )
        )
        resp.assigned_provider_count = int(cr.scalar_one() or 0)
    return resp


@router.patch("/me", response_model=UserResponse)
async def update_me(
    req: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.full_name is not None:
        current_user.full_name = req.full_name
    if req.avatar_url is not None:
        current_user.avatar_url = req.avatar_url
    if req.avatar_emoji is not None:
        current_user.avatar_emoji = req.avatar_emoji
    if req.notes is not None:
        current_user.notes = req.notes
    if req.contact_info is not None:
        current_user.contact_info = req.contact_info
    if req.notify_email is not None:
        current_user.notify_email = req.notify_email
    if req.notify_telegram is not None:
        current_user.notify_telegram = req.notify_telegram
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("/", response_model=list[UserResponse])
async def list_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser required")
    # #174: paginate — an unbounded list of all users is an OOM risk at scale.
    result = await db.execute(
        select(User).where(User.email != "system@nexora.internal")
        .order_by(User.full_name).limit(limit).offset(offset)
    )
    return result.scalars().all()


@router.patch("/{user_id}/active")
async def set_user_active(
    user_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser required")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot modify your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = bool(body.get("is_active", True))
    db.add(target)
    await db.commit()
    return {"id": target.id, "is_active": target.is_active}


class ProfileFactResponse(BaseModel):
    id: str
    key: str
    value: str
    source: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpsertProfileFactRequest(BaseModel):
    value: str


@router.get("/me/profile-facts", response_model=list[ProfileFactResponse])
async def list_profile_facts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Structured keyed facts the AI (and the user) have recorded about this profile."""
    result = await db.execute(
        select(UserProfileFact)
        .where(UserProfileFact.user_id == current_user.id)
        .order_by(UserProfileFact.key)
    )
    return result.scalars().all()


@router.put("/me/profile-facts/{key}", response_model=ProfileFactResponse)
async def upsert_profile_fact(
    key: str,
    req: UpsertProfileFactRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    key = key.strip()
    value = req.value.strip()
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    if not value:
        raise HTTPException(status_code=400, detail="value is required (use DELETE to remove a fact)")

    result = await db.execute(
        select(UserProfileFact).where(
            UserProfileFact.user_id == current_user.id,
            UserProfileFact.key == key,
        )
    )
    fact = result.scalar_one_or_none()
    if fact:
        fact.value = value
        fact.source = "manual"
        fact.updated_at = datetime.now(timezone.utc)
    else:
        fact = UserProfileFact(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            key=key,
            value=value,
            source="manual",
        )
    db.add(fact)
    await db.commit()
    await db.refresh(fact)
    return fact


@router.delete("/me/profile-facts/{key}", status_code=204)
async def delete_profile_fact(
    key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfileFact).where(
            UserProfileFact.user_id == current_user.id,
            UserProfileFact.key == key.strip(),
        )
    )
    fact = result.scalar_one_or_none()
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")
    await db.delete(fact)
    await db.commit()


@router.get("/me/marketplace-key")
async def get_marketplace_key(current_user: User = Depends(get_current_user)):
    """Returns whether a marketplace API key is configured (not the key itself)."""
    return {"configured": bool(current_user.marketplace_api_key_enc)}


@router.put("/me/marketplace-key", status_code=204)
async def set_marketplace_key(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store or clear the user's NexoraMarketplace personal API key (encrypted)."""
    from src.core.security import encrypt
    key: str = body.get("key", "").strip()
    current_user.marketplace_api_key_enc = encrypt(key) if key else None
    db.add(current_user)
    await db.commit()


@router.patch("/me/password", status_code=204)
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change your own password. The current password is always required.

    A user can never grant themselves password sign-in: an account provisioned without
    one (CLI onboarding) must have it enabled by an org owner/admin, who hands over the
    generated password. From then on the user changes it here.
    """
    if not getattr(current_user, "has_password", True):
        raise HTTPException(
            status_code=400,
            detail="Password sign-in is not enabled for this account. "
                   "Ask your organization admin to enable it.",
        )
    if not req.current_password or not verify_password(
        req.current_password, current_user.hashed_password
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(req.new_password)
    current_user.token_version = (current_user.token_version or 0) + 1
    db.add(current_user)
    await db.commit()
