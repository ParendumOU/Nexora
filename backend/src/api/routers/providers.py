import asyncio
import uuid
import json
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, update
from pydantic import BaseModel, Field
from src.core.database import get_db
from src.core.security import encrypt, decrypt
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.provider import Provider, ProviderChain, ProviderChainItem

router = APIRouter(prefix="/providers", tags=["providers"])
logger = logging.getLogger(__name__)

_REDIS_TTL = 21600  # 6 hours


def _fallback_models(provider_type: str) -> list[str]:
    """Return the seed-defined model list for a provider type."""
    from src.seeds.loader import get_provider
    pdef = get_provider(provider_type)
    return list(pdef.get("models", [])) if pdef else []


# ── Live model fetch ──────────────────────────────────────────────────────────

async def _fetch_models_live(provider: Provider) -> list[str]:
    """
    Call the provider's official models endpoint. Returns the live list or [] on error.
    OAuth-only providers (claude/gemini/codex) cannot be queried this way — skip them.
    """
    from src.seeds.loader import get_provider as _get_pdef

    ptype = provider.provider_type

    # OAuth CLI providers: credentials live on disk, not an API key we can use
    if provider.auth_type == "oauth":
        return []

    try:
        raw = decrypt(provider.credentials) if provider.credentials else "{}"
        creds = json.loads(raw)
        api_key = creds.get("api_key", "")

        pdef = _get_pdef(ptype) or {}
        seed_base_url: str | None = pdef.get("base_url")

        # ── Ollama: local REST, no auth ─────────────────────────────────────
        if ptype == "ollama":
            base = (provider.base_url or seed_base_url or "http://localhost:11434").rstrip("/")
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(f"{base}/api/tags")
                r.raise_for_status()
                data = r.json()
                names = [m["name"] for m in data.get("models", [])]
                return names or []

        # ── All other providers: OpenAI-compatible /v1/models ───────────────
        base = (provider.base_url or seed_base_url or "").rstrip("/")
        if not base:
            return []

        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
            data = r.json()
            ids = [m["id"] for m in data.get("data", [])]
            return sorted(ids) if ids else []

    except Exception as exc:
        logger.debug("Model fetch failed for %s/%s: %s", ptype, provider.id, exc)
        return []


async def _get_provider_models(provider: Provider) -> list[str]:
    """Redis cache → live fetch → static fallback. Never raises."""
    cache_key = f"provider_models:{provider.id}"
    try:
        from src.core.redis import get_redis
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    # Cache miss — fetch live, then cache in background
    live = await _fetch_models_live(provider)
    if live:
        asyncio.create_task(_store_models_cache(cache_key, live))
        return live

    return _fallback_models(provider.provider_type)


async def _store_models_cache(key: str, models: list[str]) -> None:
    try:
        from src.core.redis import get_redis
        redis = get_redis()
        await redis.set(key, json.dumps(models), ex=_REDIS_TTL)
    except Exception:
        pass


async def _prime_models_cache(provider: Provider) -> None:
    """Fire-and-forget: fetch models and warm the cache right after provider creation."""
    live = await _fetch_models_live(provider)
    models = live or _fallback_models(provider.provider_type)
    await _store_models_cache(f"provider_models:{provider.id}", models)


# ── Response helpers ──────────────────────────────────────────────────────────

def _cooling_remaining(p: Provider) -> int:
    """Seconds until this account's durable cooldown clears (0 if not cooling)."""
    cu = p.cooling_until
    if not cu:
        return 0
    from datetime import datetime, timezone
    if cu.tzinfo is None:
        cu = cu.replace(tzinfo=timezone.utc)
    delta = (cu - datetime.now(timezone.utc)).total_seconds()
    return int(delta) if delta > 0 else 0


def _to_response(p: Provider, available_models: list[str]) -> "ProviderResponse":
    return ProviderResponse(
        id=p.id, name=p.name, provider_type=p.provider_type,
        auth_type=p.auth_type, base_url=p.base_url, model_name=p.model_name,
        is_active=p.is_active, cooldown_seconds=p.cooldown_seconds,
        priority=p.priority, auth_path=p.auth_path,
        available_models=available_models,
        last_error=p.last_error,
        last_error_at=p.last_error_at.isoformat() if p.last_error_at else None,
        last_used_at=p.last_used_at.isoformat() if p.last_used_at else None,
        state=p.state,
        cooling_until=p.cooling_until.isoformat() if p.cooling_until else None,
        cooling_remaining_seconds=_cooling_remaining(p),
        consecutive_failures=p.consecutive_failures,
        assigned_user_id=p.assigned_user_id,
        created_by_user_id=p.created_by_user_id,
    )


# ── Auth / DB helpers ─────────────────────────────────────────────────────────


# ── Pydantic models ───────────────────────────────────────────────────────────

class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider_type: str = Field(..., max_length=50)
    auth_type: str = "apikey"
    credentials: dict = {}
    base_url: str | None = Field(None, max_length=2048)
    model_name: str | None = Field(None, max_length=255)
    cooldown_seconds: int = Field(60, ge=1, le=86400)


class ProviderResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    auth_type: str
    base_url: str | None
    model_name: str | None
    is_active: bool
    cooldown_seconds: int
    priority: int
    auth_path: str | None = None
    available_models: list[str] = []
    last_error: str | None = None
    last_error_at: str | None = None
    last_used_at: str | None = None
    state: str = "healthy"
    cooling_until: str | None = None
    cooling_remaining_seconds: int = 0
    consecutive_failures: int = 0
    assigned_user_id: str | None = None
    created_by_user_id: str | None = None

    model_config = {"from_attributes": True}


class ChainStepInput(BaseModel):
    provider_type: str
    model_name: str | None = None


class ChainCreate(BaseModel):
    name: str
    steps: list[ChainStepInput]
    is_default: bool = False


class ChainStepResponse(BaseModel):
    position: int
    provider_type: str
    model_name: str | None
    account_count: int = 0


class ChainResponse(BaseModel):
    id: str
    name: str
    is_default: bool
    steps: list[ChainStepResponse]

    model_config = {"from_attributes": True}


# ── Provider catalog (seed-defined types) ────────────────────────────────────

class ProviderTypeInfo(BaseModel):
    key: str
    name: str
    description: str
    auth_type: str
    stream_type: str
    base_url: str | None
    requires_base_url: bool
    default_model: str | None
    models: list[str]
    website: str | None
    category: str


@router.get("/catalog", response_model=list[ProviderTypeInfo])
async def list_provider_catalog(
    current_user: User = Depends(get_current_user),
):
    """Return all provider types defined in seeds — used by the UI to populate provider creation forms."""
    from src.seeds.loader import get_all_providers
    return [
        ProviderTypeInfo(
            key=p.get("key", ""),
            name=p.get("name", ""),
            description=p.get("description", ""),
            auth_type=p.get("auth_type", "apikey"),
            stream_type=p.get("stream_type", "openai_compat"),
            base_url=p.get("base_url"),
            requires_base_url=p.get("requires_base_url", False),
            default_model=p.get("default_model"),
            models=p.get("models", []),
            website=p.get("website"),
            category=p.get("_category", "api"),
        )
        for p in get_all_providers()
    ]


# ── Provider CRUD ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[ProviderResponse])
async def list_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(select(Provider).where(Provider.org_id == org_id))
    from src.core.permissions import filter_by_capability
    providers = await filter_by_capability(
        current_user, org_id, db, list(result.scalars().all()), "provider_ids", lambda p: p.id,
    )
    # Per-member governance: a restricted member only sees the accounts they may use
    # (their assigned accounts + pool, per provider mode). Owners/admins see all.
    from src.services.provider_policy import usable_provider_ids
    allowed = await usable_provider_ids(current_user, org_id, db)
    if allowed is not None:
        providers = [p for p in providers if p.id in allowed]
    models_list = await asyncio.gather(*[_get_provider_models(p) for p in providers])
    return [_to_response(p, m) for p, m in zip(providers, models_list)]


@router.get("/availability")
async def get_provider_availability(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-account availability snapshot — which accounts are usable now and, for any
    that are cooling, when they come back. Powers the 'can we work / when' indicators
    in the UI and the availability hint agents see when delegating."""
    org_id = await get_active_org_id(current_user, db)
    from src.services.agent_context.providers import provider_availability
    snapshot = await provider_availability(org_id, db=db)
    usable = sum(1 for s in snapshot if s["available"])
    return {
        "accounts": snapshot,
        "usable_count": usable,
        "cooling_count": len(snapshot) - usable,
        "any_usable": usable > 0,
    }


@router.post("", response_model=ProviderResponse, status_code=201)
async def create_provider(
    req: ProviderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    encrypted = encrypt(json.dumps(req.credentials)) if req.credentials else None
    provider = Provider(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=req.name,
        provider_type=req.provider_type,
        auth_type=req.auth_type,
        credentials=encrypted,
        base_url=req.base_url,
        model_name=req.model_name,
        cooldown_seconds=req.cooldown_seconds,
        created_by_user_id=current_user.id,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    # Warm model cache in background; return fallback immediately
    asyncio.create_task(_prime_models_cache(provider))
    return _to_response(provider, _fallback_models(provider.provider_type))


class ProviderUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    base_url: str | None = Field(None, max_length=2048)
    model_name: str | None = Field(None, max_length=255)
    credentials: dict | None = None
    cooldown_seconds: int | None = Field(None, ge=1, le=86400)
    is_active: bool | None = None


@router.patch("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str,
    req: ProviderUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id, Provider.org_id == org_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if req.name is not None:
        provider.name = req.name
    if req.base_url is not None:
        provider.base_url = req.base_url or None
    if req.model_name is not None:
        provider.model_name = req.model_name or None
    if req.cooldown_seconds is not None:
        provider.cooldown_seconds = req.cooldown_seconds
    if req.is_active is not None:
        provider.is_active = req.is_active
    if req.credentials:
        provider.credentials = encrypt(json.dumps(req.credentials))
        # Invalidate cached models so they're re-fetched with new credentials
        asyncio.create_task(_prime_models_cache(provider))

    await db.commit()
    await db.refresh(provider)
    models = await _get_provider_models(provider)
    return _to_response(provider, models)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id, Provider.org_id == org_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider.is_active = False
    await db.commit()


@router.delete("/{provider_id}/purge", status_code=204)
async def purge_provider(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id, Provider.org_id == org_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    from src.models.chat import Chat
    await db.execute(
        update(Chat)
        .where(Chat.direct_provider_id == provider_id)
        .values(direct_provider_id=None)
    )
    await db.delete(provider)
    await db.commit()


class ProviderHealthResponse(BaseModel):
    status: str
    model: str | None
    latency_ms: float | None
    error: str | None


@router.post("/{provider_id}/health", response_model=ProviderHealthResponse)
async def provider_health(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import time
    from src.seeds.loader import get_provider as _get_pdef

    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id, Provider.org_id == org_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if provider.auth_type == "oauth":
        return ProviderHealthResponse(
            status="error", model=None, latency_ms=None,
            error="Health check not supported for OAuth providers",
        )

    pdef = _get_pdef(provider.provider_type) or {}
    seed_base_url: str | None = pdef.get("base_url")
    base = (provider.base_url or seed_base_url or "").rstrip("/")

    try:
        raw = decrypt(provider.credentials) if provider.credentials else "{}"
        creds = json.loads(raw)
        api_key: str = creds.get("api_key", "")
    except Exception:
        api_key = ""

    models_list: list[str] = pdef.get("models", [])
    model: str | None = provider.model_name or pdef.get("default_model") or (models_list[0] if models_list else None)

    start = time.monotonic()
    try:
        if provider.provider_type == "ollama":
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{base}/api/tags")
                r.raise_for_status()
        else:
            if not base:
                return ProviderHealthResponse(
                    status="error", model=model, latency_ms=None,
                    error="No base URL configured for this provider",
                )
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                        "stream": False,
                    },
                )
                r.raise_for_status()

        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return ProviderHealthResponse(status="ok", model=model, latency_ms=latency_ms, error=None)

    except httpx.HTTPStatusError as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        try:
            detail = exc.response.json()
            err_msg = (detail.get("error") or {}).get("message") or str(detail)
        except Exception:
            err_msg = exc.response.text[:300]
        return ProviderHealthResponse(status="error", model=model, latency_ms=latency_ms, error=err_msg)

    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return ProviderHealthResponse(status="error", model=model, latency_ms=latency_ms, error=str(exc))


@router.patch("/{provider_id}/restore", status_code=200)
async def restore_provider(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id, Provider.org_id == org_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider.is_active = True
    await db.commit()
    return {"id": provider.id, "is_active": True}


# ── Per-member assignment (owner/admin) ──────────────────────────────────────

class ProviderAssignRequest(BaseModel):
    # null unassigns the account back into the shared pool.
    user_id: str | None = None


class ProviderAssignmentResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    is_active: bool
    assigned_user_id: str | None = None
    assignee_email: str | None = None
    assignee_name: str | None = None
    created_by_user_id: str | None = None


@router.get("/assignments", response_model=list[ProviderAssignmentResponse])
async def list_provider_assignments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner/admin view of every account in the active org and who it's reserved to."""
    from src.core.permissions import require_org_role
    from src.models.org import OrgRole

    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.admin, db)

    rows = list(
        (await db.execute(select(Provider).where(Provider.org_id == org_id))).scalars().all()
    )
    assignee_ids = {p.assigned_user_id for p in rows if p.assigned_user_id}
    users: dict[str, User] = {}
    if assignee_ids:
        ur = await db.execute(select(User).where(User.id.in_(assignee_ids)))
        users = {u.id: u for u in ur.scalars().all()}

    out = []
    for p in rows:
        u = users.get(p.assigned_user_id) if p.assigned_user_id else None
        out.append(ProviderAssignmentResponse(
            id=p.id, name=p.name, provider_type=p.provider_type, is_active=p.is_active,
            assigned_user_id=p.assigned_user_id,
            assignee_email=u.email if u else None,
            assignee_name=u.full_name if u else None,
            created_by_user_id=p.created_by_user_id,
        ))
    return out


@router.post("/{provider_id}/assign", response_model=ProviderResponse)
async def assign_provider(
    provider_id: str,
    req: ProviderAssignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reserve an account to one member (exclusive), or release it (user_id=null)."""
    from src.core.permissions import require_org_role
    from src.models.org import OrgMember, OrgRole

    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.admin, db)

    result = await db.execute(
        select(Provider).where(Provider.id == provider_id, Provider.org_id == org_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    target_id = req.user_id or None
    if target_id:
        m = await db.execute(
            select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == target_id)
        )
        if not m.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Target user is not a member of this organization")

    provider.assigned_user_id = target_id
    await db.commit()
    await db.refresh(provider)
    models = await _get_provider_models(provider)
    return _to_response(provider, models)


# ── Chain CRUD ────────────────────────────────────────────────────────────────

async def _account_counts(org_id: str, db: AsyncSession) -> dict[str, int]:
    r = await db.execute(
        select(Provider.provider_type, func.count(Provider.id))
        .where(Provider.org_id == org_id, Provider.is_active == True)  # noqa: E712
        .group_by(Provider.provider_type)
    )
    return dict(r.all())


def _chain_resp(chain: ProviderChain, counts: dict[str, int]) -> ChainResponse:
    steps = [
        ChainStepResponse(
            position=item.position,
            provider_type=item.provider_type,
            model_name=item.model_name,
            account_count=counts.get(item.provider_type, 0),
        )
        for item in chain.items
    ]
    return ChainResponse(id=chain.id, name=chain.name, is_default=chain.is_default, steps=steps)


@router.get("/chains", response_model=list[ChainResponse])
async def list_chains(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(select(ProviderChain).where(ProviderChain.org_id == org_id))
    # "__solo__*" chains are internal single-account pins (created when a chat is
    # tied to one specific account); they are never shown as fallback options in
    # any client. Resolution still works by id, so hiding them here is safe.
    rows = [c for c in result.unique().scalars().all() if not (c.name or "").startswith("__solo__")]
    from src.core.permissions import filter_by_capability
    chains = await filter_by_capability(
        current_user, org_id, db, rows, "chain_ids", lambda c: c.id,
    )
    counts = await _account_counts(org_id, db)
    return [_chain_resp(c, counts) for c in chains]


@router.post("/chains", response_model=ChainResponse, status_code=201)
async def create_chain(
    req: ChainCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    chain = ProviderChain(id=str(uuid.uuid4()), org_id=org_id, name=req.name, is_default=req.is_default)
    db.add(chain)
    await db.flush()
    for i, step in enumerate(req.steps):
        db.add(ProviderChainItem(
            id=str(uuid.uuid4()), chain_id=chain.id,
            provider_type=step.provider_type, position=i,
            model_name=step.model_name,
        ))
    await db.commit()
    await db.refresh(chain)
    counts = await _account_counts(org_id, db)
    return _chain_resp(chain, counts)


class ChainUpdate(BaseModel):
    name: str | None = None
    is_default: bool | None = None
    steps: list[ChainStepInput] | None = None


@router.patch("/chains/{chain_id}", response_model=ChainResponse)
async def update_chain(
    chain_id: str,
    req: ChainUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(ProviderChain).where(ProviderChain.id == chain_id, ProviderChain.org_id == org_id)
    )
    chain = result.unique().scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    if req.name is not None:
        chain.name = req.name
    if req.is_default is not None:
        chain.is_default = req.is_default
    if req.steps is not None:
        await db.execute(
            delete(ProviderChainItem).where(ProviderChainItem.chain_id == chain_id),
            execution_options={"synchronize_session": False},
        )
        for i, step in enumerate(req.steps):
            db.add(ProviderChainItem(
                id=str(uuid.uuid4()), chain_id=chain.id,
                provider_type=step.provider_type, position=i,
                model_name=step.model_name,
            ))

    await db.commit()
    await db.refresh(chain)
    counts = await _account_counts(org_id, db)
    return _chain_resp(chain, counts)


@router.delete("/chains/{chain_id}", status_code=204)
async def delete_chain(
    chain_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(ProviderChain).where(ProviderChain.id == chain_id, ProviderChain.org_id == org_id)
    )
    chain = result.unique().scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")
    await db.delete(chain)
    await db.commit()


# ── OAuth ─────────────────────────────────────────────────────────────────────

class OAuthStartRequest(BaseModel):
    provider_type: str
    account_name: str
    model_name: str | None = None


class OAuthCodeRequest(BaseModel):
    code: str



@router.post("/auth/start")
async def start_oauth_login(
    req: OAuthStartRequest,
    current_user: User = Depends(get_current_user),
):
    from src.providers.oauth_sessions import start_login
    try:
        result = start_login(req.provider_type, req.account_name)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("OAuth start failed for %s: %s", req.provider_type, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start login")


@router.get("/auth/{provider}/status/{account_name}")
async def get_oauth_status(
    provider: str,
    account_name: str,
    current_user: User = Depends(get_current_user),
):
    from src.providers.oauth_sessions import get_status
    return get_status(provider, account_name)


@router.post("/auth/{provider}/code/{account_name}")
async def submit_oauth_code(
    provider: str,
    account_name: str,
    req: OAuthCodeRequest,
    current_user: User = Depends(get_current_user),
):
    from src.providers.oauth_sessions import submit_code
    ok = submit_code(provider, account_name, req.code)
    if not ok:
        raise HTTPException(status_code=404, detail="Auth session not found or not ready")
    return {"status": "code_submitted"}


@router.post("/auth/{provider}/complete/{account_name}", response_model=ProviderResponse, status_code=201)
async def complete_oauth_login(
    provider: str,
    account_name: str,
    req: OAuthStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Called after OAuth succeeds — creates the Provider record with stored credentials."""
    from src.providers.oauth_sessions import get_credentials, _account_home

    creds = get_credentials(provider, account_name)
    if not creds:
        raise HTTPException(status_code=400, detail="No credentials found. Authentication may have failed.")

    org_id = await get_active_org_id(current_user, db)
    auth_path = _account_home(provider, account_name)
    encrypted = encrypt(json.dumps(creds))

    db_provider = Provider(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=account_name,
        provider_type=provider,
        auth_type="oauth",
        credentials=encrypted,
        auth_path=auth_path,
        model_name=req.model_name,
        cooldown_seconds=60,
        created_by_user_id=current_user.id,
    )
    db.add(db_provider)
    await db.commit()
    await db.refresh(db_provider)
    # OAuth providers use fallback list; still prime cache so it's warm for next list call
    asyncio.create_task(_prime_models_cache(db_provider))
    return _to_response(db_provider, _fallback_models(db_provider.provider_type))
