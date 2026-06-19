import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.model_profile import ModelProfile
from src.models.provider import Provider, ProviderChain

router = APIRouter(prefix="/model-profiles", tags=["model-profiles"])


class ModelProfileCreate(BaseModel):
    name: str
    description: str | None = None
    tags: list[str] = []
    provider_type: str | None = None
    provider_chain_id: str | None = None
    model_name: str | None = None
    is_active: bool = True
    priority: int = 0


class ModelProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    provider_type: str | None = None
    provider_chain_id: str | None = None
    model_name: str | None = None
    is_active: bool | None = None
    priority: int | None = None


class ModelProfileResponse(BaseModel):
    id: str
    name: str
    description: str | None
    tags: list[str]
    provider_chain_id: str | None
    provider_type: str | None
    model_name: str | None
    is_active: bool
    priority: int = 0
    created_at: str
    chain_name: str | None = None
    account_count: int = 0

    model_config = {"from_attributes": True}


async def _enrich(profile: ModelProfile, db: AsyncSession, org_id: str) -> ModelProfileResponse:
    chain_name = None
    account_count = 0

    if profile.provider_chain_id:
        r = await db.execute(select(ProviderChain).where(ProviderChain.id == profile.provider_chain_id))
        chain = r.scalar_one_or_none()
        if chain:
            chain_name = chain.name

    if profile.provider_type:
        r = await db.execute(
            select(func.count()).select_from(Provider).where(
                Provider.org_id == org_id,
                Provider.provider_type == profile.provider_type,
                Provider.is_active == True,  # noqa: E712
            )
        )
        account_count = r.scalar_one() or 0

    return ModelProfileResponse(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        tags=profile.tags or [],
        provider_chain_id=profile.provider_chain_id,
        provider_type=profile.provider_type,
        model_name=profile.model_name,
        is_active=profile.is_active,
        created_at=profile.created_at.isoformat(),
        chain_name=chain_name,
        account_count=account_count,
        priority=profile.priority,
    )


@router.get("", response_model=list[ModelProfileResponse])
async def list_profiles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(ModelProfile)
        .where(ModelProfile.org_id == org_id)
        .order_by(ModelProfile.is_active.desc(), ModelProfile.priority.desc(), ModelProfile.name)
    )
    profiles = result.scalars().all()
    return [await _enrich(p, db, org_id) for p in profiles]


@router.post("", response_model=ModelProfileResponse, status_code=201)
async def create_profile(
    req: ModelProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    profile = ModelProfile(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=req.name,
        description=req.description,
        tags=req.tags,
        provider_type=req.provider_type or None,
        provider_chain_id=req.provider_chain_id or None,
        model_name=req.model_name or None,
        is_active=req.is_active,
        priority=req.priority,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return await _enrich(profile, db, org_id)


@router.patch("/{profile_id}", response_model=ModelProfileResponse)
async def update_profile(
    profile_id: str,
    req: ModelProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(ModelProfile).where(ModelProfile.id == profile_id, ModelProfile.org_id == org_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Model profile not found")

    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)
    return await _enrich(profile, db, org_id)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(ModelProfile).where(ModelProfile.id == profile_id, ModelProfile.org_id == org_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Model profile not found")
    await db.delete(profile)
    await db.commit()


@router.get("/resolve", response_model=ModelProfileResponse | None)
async def resolve_profile(
    tags: str = "",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find the active profile with the most matching tags."""
    org_id = await get_active_org_id(current_user, db)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    result = await db.execute(
        select(ModelProfile)
        .where(ModelProfile.org_id == org_id, ModelProfile.is_active == True)  # noqa: E712
        .order_by(ModelProfile.name)
    )
    profiles = result.scalars().all()

    best: ModelProfile | None = None
    best_score = -1
    for p in profiles:
        score = len(set(p.tags or []) & set(tag_list))
        if score > best_score:
            best_score = score
            best = p

    if not best:
        return None
    return await _enrich(best, db, org_id)
