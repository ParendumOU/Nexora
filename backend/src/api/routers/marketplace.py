"""Marketplace API — browse and install community skills, tools, agents, and personas."""
import logging
import shutil
import uuid as _uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db, get_active_org_id
from src.api.routers.seeds import write_custom_seed
from src.models.user import User
from src.models.marketplace import MarketplaceItem
from src.models.skill import Skill
from src.models.tool import Tool
from src.models.persona import Persona
from src.models.agent import Agent
from src.models.installed_package import InstalledPackage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/marketplace", tags=["marketplace"])

VALID_TYPES = {"skill", "tool", "agent", "persona"}

# Marketplace liability signal (GitLab #158). A non-standard warning requires the
# caller to explicitly acknowledge the risk before the package will install.
NONSTANDARD_WARNINGS = {"elevated", "high"}


def _utcnow():
    return datetime.now(timezone.utc)


def _parse_risk(data: dict) -> dict:
    """Extract the coarse marketplace liability signal from fetched package
    metadata (GitLab #158). Tolerant by design: when the fields are absent
    (older/other marketplace) we treat the package as safe — warning_level
    "standard" / trust_tier "established" — so existing imports never break."""
    warning_level = str(data.get("warning_level") or "standard").lower()
    trust_tier = str(data.get("trust_tier") or "established").lower()
    return {
        "warning_level": warning_level,
        "trust_tier": trust_tier,
        "below_like_threshold": bool(data.get("below_like_threshold")),
        "below_download_threshold": bool(data.get("below_download_threshold")),
    }


async def _fetch_disclaimer(origin: str, headers: dict) -> str:
    """Fetch the marketplace's static third-party-content disclaimer
    (`GET /api/packages/disclaimer`). Falls back to the bundled seed text when
    the marketplace doesn't serve one (older/other marketplace, transport error)."""
    from src.seeds.loader import get_prompt
    fallback = get_prompt("marketplace_disclaimer_fallback").strip()
    if origin:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{origin.rstrip('/')}/api/packages/disclaimer", headers=headers)
            if resp.status_code == 200:
                text = (resp.json() or {}).get("disclaimer")
                if text:
                    return str(text)
        except Exception:  # noqa: BLE001 — disclaimer is best-effort; fall back
            pass
    return fallback


async def record_install(
    db: AsyncSession,
    org_id: str,
    item_type: str,
    data: dict,
    origin: str,
    risk: "dict | None" = None,
) -> None:
    """Record/refresh provenance for an installed marketplace item so the
    update-checker can later compare against the marketplace's current version.
    Keyed by (org_id, item_type, source_slug). Best-effort — never raises into
    the import flow.

    `risk` (optional, GitLab #158) carries the marketplace liability signal at
    install time: `{trust_tier, warning_level, acknowledged}`. When omitted the
    safe defaults (established/standard/not-acknowledged) are used."""
    try:
        slug = data.get("slug") or data.get("key") or ""
        if not slug or item_type not in VALID_TYPES or not origin:
            return
        name = data.get("name") or slug
        version = str(data.get("version") or "1.0.0")
        pricing = data.get("pricing_type") or "free"
        risk = risk or {}
        trust_tier = str(risk.get("trust_tier") or "established")
        warning_level = str(risk.get("warning_level") or "standard")
        acknowledged = bool(risk.get("acknowledged"))
        ack_at = _utcnow() if acknowledged else None
        existing = (await db.execute(
            select(InstalledPackage).where(
                InstalledPackage.org_id == org_id,
                InstalledPackage.item_type == item_type,
                InstalledPackage.source_slug == slug,
            )
        )).scalar_one_or_none()
        if existing:
            existing.installed_version = version
            existing.origin = origin
            existing.name = name
            existing.pricing_type = pricing
            existing.available_version = None  # cleared; next check re-evaluates
            existing.trust_tier = trust_tier
            existing.warning_level = warning_level
            existing.risk_acknowledged = acknowledged
            existing.risk_acknowledged_at = ack_at
        else:
            db.add(InstalledPackage(
                org_id=org_id, item_type=item_type, source_slug=slug, origin=origin,
                name=name, installed_version=version, pricing_type=pricing,
                trust_tier=trust_tier, warning_level=warning_level,
                risk_acknowledged=acknowledged, risk_acknowledged_at=ack_at,
            ))
    except Exception as exc:  # noqa: BLE001 — provenance must never break an install
        logger.debug("[marketplace] record_install failed for %s/%s: %s", item_type, data.get("slug"), exc)


def _agent_seed_key(slug: str, name: str = "") -> str:
    """Canonical custom-seed directory key for an imported agent."""
    return (slug or name).lower().replace(" ", "_")


def _item_to_dict(item: MarketplaceItem, installed: bool = False) -> dict:
    return {
        "id": item.id,
        "slug": item.slug,
        "name": item.name,
        "type": item.item_type,
        "description": item.description,
        "author": item.author,
        "version": item.version,
        "tags": item.tags or [],
        "is_builtin": item.is_builtin,
        "install_count": item.install_count,
        "icon": item.icon,
        "installed": installed,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("")
async def list_marketplace(
    q: str = Query("", description="Search name/description"),
    item_type: str = Query("", description="Filter by type: skill|tool|agent|persona"),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org_id = await get_active_org_id(current_user, db)

    base = select(MarketplaceItem).where(MarketplaceItem.is_active == True)

    if q.strip():
        term = f"%{q.strip()}%"
        base = base.where(
            or_(MarketplaceItem.name.ilike(term), MarketplaceItem.description.ilike(term))
        )
    if item_type and item_type in VALID_TYPES:
        base = base.where(MarketplaceItem.item_type == item_type)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    items = (await db.execute(base.order_by(MarketplaceItem.install_count.desc(), MarketplaceItem.name).offset((page - 1) * per_page).limit(per_page))).scalars().all()

    # Determine which items the org already has installed
    installed_skill_keys = {
        r for (r,) in (await db.execute(select(Skill.key).where(Skill.org_id == org_id))).fetchall()
    }
    installed_tool_keys = {
        r for (r,) in (await db.execute(select(Tool.key).where(Tool.org_id == org_id))).fetchall()
    }

    def _is_installed(item: MarketplaceItem) -> bool:
        if item.item_type == "skill":
            return item.slug in installed_skill_keys or item.is_builtin
        if item.item_type == "tool":
            return item.slug in installed_tool_keys or item.is_builtin
        return item.is_builtin  # agents/personas: builtin = always available

    result = [_item_to_dict(i, _is_installed(i)) for i in items]
    return {"items": result, "total": total, "page": page, "per_page": per_page}


@router.get("/public/{slug}")
async def get_marketplace_item_public(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Public (unauthenticated) endpoint — returns item metadata for import links."""
    r = await db.execute(select(MarketplaceItem).where(MarketplaceItem.slug == slug, MarketplaceItem.is_active == True))
    item = r.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return _item_to_dict(item)


class ImportRequest(BaseModel):
    url: str
    # GitLab #158 — explicit risk acknowledgment for low-reputation packages.
    # Required (True) to proceed when the marketplace flags the package
    # warning_level as elevated/high; ignored for standard packages.
    acknowledge_risk: bool = False


def _marketplace_headers(current_user: User) -> dict:
    """Build the Authorization header for marketplace requests from the user's
    stored (Fernet-encrypted) marketplace API key, if any. Used so private
    packages — and an imported agent's private sub-dependencies — resolve."""
    from src.core.security import decrypt
    headers: dict = {}
    if current_user.marketplace_api_key_enc:
        try:
            api_key = decrypt(current_user.marketplace_api_key_enc)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        except Exception:
            pass
    return headers


async def _install_dependency_package(
    dep_type: str, dep_data: dict, org_id: str, db: AsyncSession
) -> str | None:
    """Create the org-scoped Skill/Tool/Persona row for a fetched dependency
    package, mirroring the skill/tool/persona branches of the main import.
    Returns None on success, or a short reason string if it was skipped/failed
    (the caller already filters out deps that are present, so any reason here is
    informational). Agent deps are not auto-installed recursively — only the
    leaf capability types (skill/tool/persona) are."""
    dep_slug = dep_data.get("slug") or dep_data.get("key", "")
    dep_name = dep_data.get("name", dep_slug)
    dep_desc = dep_data.get("description", "")
    dep_version_category = dep_data.get("category", "community")

    if dep_type == "skill":
        existing = await db.execute(select(Skill).where(Skill.org_id == org_id, Skill.key == dep_slug))
        if existing.scalar_one_or_none():
            return "already installed"
        # Materialize the package files on disk so the seed loader can discover
        # the skill's manifest/executor — without this the DB row points at a
        # definition that does not exist and the skill cannot run.
        write_custom_seed("skill", dep_slug, dep_data.get("files") or {}, dep_data.get("manifest") or {})
        from src.seeds.loader import get_skill
        seed = get_skill(dep_slug) or {}
        db.add(Skill(
            id=str(_uuid.uuid4()),
            org_id=org_id,
            key=dep_slug,
            name=dep_name,
            description=dep_desc,
            category=seed.get("category", dep_version_category),
            is_builtin=False,
        ))
        return None

    if dep_type == "tool":
        existing = await db.execute(select(Tool).where(Tool.org_id == org_id, Tool.key == dep_slug))
        if existing.scalar_one_or_none():
            return "already installed"
        write_custom_seed("tool", dep_slug, dep_data.get("files") or {}, dep_data.get("manifest") or {})
        from src.seeds.loader import get_tool
        seed = get_tool(dep_slug) or {}
        db.add(Tool(
            id=str(_uuid.uuid4()),
            org_id=org_id,
            key=dep_slug,
            name=dep_name,
            description=dep_desc,
            category=seed.get("category", dep_version_category),
        ))
        return None

    if dep_type == "persona":
        manifest = dep_data.get("manifest") or {}
        key = dep_slug.lower().replace(" ", "_")
        existing = await db.execute(select(Persona).where(Persona.org_id == org_id, Persona.key == key))
        if existing.scalar_one_or_none():
            return "already installed"
        write_custom_seed("persona", key, dep_data.get("files") or {}, manifest)
        from src.seeds.loader import get_persona
        seed = get_persona(key) or {}
        db.add(Persona(
            id=str(_uuid.uuid4()),
            org_id=org_id,
            key=key,
            name=dep_name,
            description=dep_desc,
            icon=manifest.get("icon") or dep_data.get("icon") or seed.get("icon"),
            soul=manifest.get("soul") or dep_data.get("soul") or seed.get("soul") or {},
            system_prompt=manifest.get("system_prompt") or dep_data.get("system_prompt") or seed.get("system_prompt"),
            default_skills=manifest.get("default_skills") or dep_data.get("default_skills") or seed.get("default_skills") or [],
            default_tools=manifest.get("default_tools") or dep_data.get("default_tools") or seed.get("default_tools") or [],
            default_mcps=manifest.get("default_mcps") or dep_data.get("default_mcps") or seed.get("default_mcps") or [],
        ))
        return None

    return f"unsupported dependency type: {dep_type}"


def _dep_url_for(import_url: str, slug: str) -> str:
    """Derive the package-metadata URL for a sub-dependency `slug` from the
    original import URL, which has the shape `{origin}/api/packages/{parent}`.
    We replace only the trailing path segment so the same origin + path prefix
    (and therefore the same marketplace) is reused."""
    base, _, _last = import_url.rstrip("/").rpartition("/")
    if base:
        return f"{base}/{slug}"
    return import_url


def _origin_of(url: str) -> str:
    """Return everything before `/api/` in a marketplace URL, so sibling
    endpoints can be built regardless of the path the import URL used
    (`/api/packages/...` for items vs `/api/starter-packs/...` for packs)."""
    marker = "/api/"
    idx = url.find(marker)
    if idx != -1:
        return url[:idx]
    return url.rstrip("/").rpartition("/")[0] or url


async def _create_agent_row(data: dict, org_id: str, db: AsyncSession) -> str | None:
    """Materialize an imported agent: write its seed files on disk and add the
    org-scoped Agent row. Returns None on success or a reason string if skipped
    (already installed). Does NOT resolve sub-dependencies — see
    `_install_agent_deps`."""
    manifest = data.get("manifest") or {}
    slug = data.get("slug") or data.get("key", "")
    name = data.get("name", slug)
    description = data.get("description", "")
    agent_name = manifest.get("name") or name
    existing = await db.execute(select(Agent).where(Agent.org_id == org_id, Agent.name == agent_name))
    if existing.scalar_one_or_none():
        return "already installed"

    # Per-license agent quota (no-op in OSS). Covers single-agent + pack import.
    from src.services.billing_limits import enforce_agent_quota
    await enforce_agent_quota(org_id)

    key = _agent_seed_key(slug, agent_name)
    write_custom_seed("agent", key, data.get("files") or {}, manifest)
    from src.seeds.loader import get_agent
    seed = get_agent(key) or {}

    def _f(field: str, default):
        val = manifest.get(field)
        if val is None:
            val = data.get(field)
        if val is None:
            val = seed.get(field)
        return default if val is None else val

    db.add(Agent(
        id=str(_uuid.uuid4()),
        org_id=org_id,
        name=agent_name,
        agent_type=_f("agent_type", "custom"),
        description=description or manifest.get("description") or seed.get("description"),
        soul=_f("soul", {}),
        system_prompt=_f("system_prompt", None),
        skills=_f("skills", []),
        tools=_f("tools", []),
        mcps=_f("mcps", []),
        env_vars=_f("env_vars", {}),
        max_subagents=_f("max_subagents", 5),
        max_concurrency=_f("max_concurrency", 2),
        model_pref=_f("model_pref", None),
        temperature=_f("temperature", 0.3),
        max_tokens=_f("max_tokens", 8192),
        flow_config=_f("flow_config", {}),
        is_builtin=False,
    ))
    return None


async def _install_agent_deps(
    data: dict, import_url: str, headers: dict, org_id: str, db: AsyncSession
) -> tuple[list, list, list]:
    """Resolve + install an imported agent's structured `dependencies` (leaf
    skill/tool/persona packages) from the same marketplace. Returns
    (installed, skipped, failed). Nested agent deps are recorded, not recursed."""
    manifest = data.get("manifest") or {}
    raw_deps = data.get("dependencies") or manifest.get("dependencies") or []
    installed: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    seen: set[str] = set()
    for dep in raw_deps:
        if not isinstance(dep, dict):
            continue
        dep_slug = dep.get("slug") or dep.get("key", "")
        dep_type = dep.get("package_type") or dep.get("type", "")
        if not dep_slug or dep_slug in seen:
            continue
        seen.add(dep_slug)
        if dep_type not in VALID_TYPES:
            failed.append({"slug": dep_slug, "reason": f"invalid type: {dep_type or 'unknown'}"})
            continue
        if dep_type == "agent":
            skipped.append({"slug": dep_slug, "type": dep_type, "reason": "nested agent not auto-installed"})
            continue
        try:
            async with httpx.AsyncClient(timeout=10.0) as dep_client:
                dep_resp = await dep_client.get(_dep_url_for(import_url, dep_slug), headers=headers)
            dep_resp.raise_for_status()
            dep_data = dep_resp.json()
        except httpx.HTTPStatusError as exc:
            failed.append({"slug": dep_slug, "type": dep_type, "reason": f"HTTP {exc.response.status_code}"})
            continue
        except Exception as exc:
            logger.warning("[marketplace] failed to fetch agent dep %s: %s", dep_slug, exc)
            failed.append({"slug": dep_slug, "type": dep_type, "reason": "fetch failed"})
            continue
        try:
            reason = await _install_dependency_package(dep_type, dep_data, org_id, db)
        except Exception as exc:
            logger.warning("[marketplace] failed to install agent dep %s: %s", dep_slug, exc)
            failed.append({"slug": dep_slug, "type": dep_type, "reason": str(exc)})
            continue
        if reason is None:
            await record_install(db, org_id, dep_type, dep_data, _origin_of(import_url))
            installed.append({"slug": dep_slug, "type": dep_type})
        else:
            skipped.append({"slug": dep_slug, "type": dep_type, "reason": reason})
    return installed, skipped, failed


@router.get("/registry")
async def search_registry(
    q: str = Query("", description="Search name/description"),
    item_type: str = Query("", description="skill|tool|agent|persona"),
    tags: str = Query("", description="comma-separated tags"),
    sort: str = Query("newest"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Proxy a live search to the external NexoraMarketplace registry, authenticated with
    the caller's stored marketplace API key so public + their private packages resolve.

    Unlike GET /marketplace (which lists this instance's local catalog), this returns the
    full public registry. Each item carries an `import_url` the client can feed to /import.
    """
    from src.core.config import get_settings
    base = get_settings().nexora_marketplace_url.rstrip("/")
    headers = _marketplace_headers(current_user)
    params: dict = {"page": page, "per_page": per_page, "sort": sort}
    if q.strip():
        params["q"] = q.strip()
    if item_type:
        params["type"] = item_type
    if tags.strip():
        params["tags"] = tags.strip()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/api/packages/", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Marketplace returned {exc.response.status_code}")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to reach marketplace registry")

    # Mark which registry packages are already installed in this org (skill/tool keys).
    from src.models.skill import Skill
    from src.models.tool import Tool
    installed_keys: set[str] = set()
    try:
        from src.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as _db:
            oid = await get_active_org_id(current_user, _db)
            for (k,) in (await _db.execute(select(Skill.key).where(Skill.org_id == oid))).all():
                installed_keys.add(k)
            for (k,) in (await _db.execute(select(Tool.key).where(Tool.org_id == oid))).all():
                installed_keys.add(k)
    except Exception:
        pass

    items = []
    for p in data.get("items", []):
        slug = p.get("slug", "")
        author = p.get("author") or {}
        items.append({
            "id": p.get("id", ""),
            "slug": slug,
            "name": p.get("name", slug),
            "type": p.get("package_type", ""),
            "description": p.get("description", ""),
            "author": author.get("username", "") if isinstance(author, dict) else str(author),
            "version": p.get("version", ""),
            "tags": p.get("tags") or [],
            "install_count": p.get("download_count", 0),
            "icon": p.get("icon", ""),
            "visibility": p.get("visibility", "public"),
            "installed": slug in installed_keys,
            "liked": bool(p.get("liked_by_me", False)),
            "import_url": f"{base}/api/packages/{slug}",
            "pricing_type": p.get("pricing_type") or "free",
            "price_cents": p.get("price_cents"),
            "currency": p.get("currency") or "usd",
            "entitled": bool(p.get("entitled", True)),
        })
    return {
        "items": items,
        "total": data.get("total", len(items)),
        "page": data.get("page", page),
        "per_page": data.get("per_page", per_page),
    }


@router.post("/registry/{slug}/like")
async def like_registry_package(
    slug: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Toggle a like on a registry package (proxied with the caller's marketplace key)."""
    from src.core.config import get_settings
    base = get_settings().nexora_marketplace_url.rstrip("/")
    headers = _marketplace_headers(current_user)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{base}/api/packages/{slug}/like", headers=headers)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Marketplace returned {exc.response.status_code}")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to reach marketplace registry")


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_marketplace_item(
    body: ImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch an item definition from a remote marketplace URL and install it."""
    url = str(body.url).strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    headers = _marketplace_headers(current_user)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Remote returned {exc.response.status_code}")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch import URL")

    slug = data.get("slug") or data.get("key", "")
    item_type = data.get("type") or data.get("package_type", "")
    name = data.get("name", slug)
    description = data.get("description", "")
    version = data.get("version", "1.0.0")
    category = data.get("category", "community")

    # A starter pack (bundle) has no package_type but carries an `items` list of
    # constituent packages (the `/api/starter-packs/{slug}` shape).
    is_pack = item_type == "pack" or (not item_type and isinstance(data.get("items"), list))
    if is_pack:
        item_type = "pack"

    if not slug or (not is_pack and item_type not in VALID_TYPES):
        raise HTTPException(status_code=422, detail="Invalid item data from remote URL")

    # ── Trust-tier / liability gate (GitLab #158) ───────────────────────────
    # Surface the marketplace's coarse liability signal. Absent fields → treated
    # as standard/established so existing imports never break. A non-standard
    # warning (elevated/high) requires explicit risk acknowledgment to proceed.
    origin = _origin_of(url)
    risk = _parse_risk(data)
    disclaimer = await _fetch_disclaimer(origin, headers)
    if risk["warning_level"] in NONSTANDARD_WARNINGS and not body.acknowledge_risk:
        from src.seeds.loader import get_prompt
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "risk_acknowledgment_required",
                "slug": slug,
                "type": item_type,
                "warning_level": risk["warning_level"],
                "trust_tier": risk["trust_tier"],
                "below_like_threshold": risk["below_like_threshold"],
                "below_download_threshold": risk["below_download_threshold"],
                "disclaimer": disclaimer,
                "message": get_prompt("marketplace_risk_ack").strip(),
            },
        )

    # The acknowledgment recorded against the install (only meaningful for a
    # non-standard package; harmless to pass through for standard ones).
    risk_record = {
        "trust_tier": risk["trust_tier"],
        "warning_level": risk["warning_level"],
        "acknowledged": bool(body.acknowledge_risk) and risk["warning_level"] in NONSTANDARD_WARNINGS,
    }

    org_id = await get_active_org_id(current_user, db)

    # Populated by the agent branch when it auto-resolves sub-dependencies.
    dep_installed: list[dict] = []
    dep_skipped: list[dict] = []
    dep_failed: list[dict] = []
    dep_note: str | None = None

    if item_type == "skill":
        existing = await db.execute(select(Skill).where(Skill.org_id == org_id, Skill.key == slug))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Skill already installed")
        # Materialize package files on disk so the seed loader can discover the
        # skill definition/executor (the DB row alone is not runnable).
        write_custom_seed("skill", slug, data.get("files") or {}, data.get("manifest") or {})
        from src.seeds.loader import get_skill
        seed = get_skill(slug) or {}
        db.add(Skill(
            id=str(_uuid.uuid4()),
            org_id=org_id,
            key=slug,
            name=name,
            description=description,
            category=seed.get("category", category),
            is_builtin=False,
        ))
        await record_install(db, org_id, "skill", data, origin, risk_record)

    elif item_type == "tool":
        existing = await db.execute(select(Tool).where(Tool.org_id == org_id, Tool.key == slug))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Tool already installed")
        write_custom_seed("tool", slug, data.get("files") or {}, data.get("manifest") or {})
        from src.seeds.loader import get_tool
        seed = get_tool(slug) or {}
        db.add(Tool(
            id=str(_uuid.uuid4()),
            org_id=org_id,
            key=slug,
            name=name,
            description=description,
            category=seed.get("category", category),
        ))
        await record_install(db, org_id, "tool", data, origin, risk_record)

    elif item_type == "persona":
        # Rich fields (soul, system_prompt, defaults) live in the package manifest
        # when present; fall back to flat payload keys otherwise.
        manifest = data.get("manifest") or {}
        key = slug.lower().replace(" ", "_")
        existing = await db.execute(select(Persona).where(Persona.org_id == org_id, Persona.key == key))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Persona already installed")
        write_custom_seed("persona", key, data.get("files") or {}, manifest)
        from src.seeds.loader import get_persona
        seed = get_persona(key) or {}
        db.add(Persona(
            id=str(_uuid.uuid4()),
            org_id=org_id,
            key=key,
            name=name,
            description=description,
            icon=manifest.get("icon") or data.get("icon") or seed.get("icon"),
            soul=manifest.get("soul") or data.get("soul") or seed.get("soul") or {},
            system_prompt=manifest.get("system_prompt") or data.get("system_prompt") or seed.get("system_prompt"),
            default_skills=manifest.get("default_skills") or data.get("default_skills") or seed.get("default_skills") or [],
            default_tools=manifest.get("default_tools") or data.get("default_tools") or seed.get("default_tools") or [],
            default_mcps=manifest.get("default_mcps") or data.get("default_mcps") or seed.get("default_mcps") or [],
        ))
        await record_install(db, org_id, "persona", data, origin, risk_record)

    elif item_type == "agent":
        # Write the agent seed + DB row, then auto-install its structured
        # `dependencies` (leaf skill/tool/persona packages) from the same
        # marketplace. Nested agent deps are recorded, not recursed.
        reason = await _create_agent_row(data, org_id, db)
        if reason == "already installed":
            raise HTTPException(status_code=409, detail="Agent already installed")
        await record_install(db, org_id, "agent", data, origin, risk_record)
        dep_installed, dep_skipped, dep_failed = await _install_agent_deps(data, url, headers, org_id, db)
        if not (data.get("dependencies") or (data.get("manifest") or {}).get("dependencies")):
            # No resolvable dependency metadata; the agent's flat skills/tools
            # (bare keys) may reference capabilities that are not installed.
            dep_note = (
                "Package carried no resolvable dependency metadata; the agent's "
                "referenced skills/tools (if any) must be installed separately."
            )

    elif item_type == "pack":
        # A starter pack installs each constituent package. Items use the
        # `/api/starter-packs/{slug}` shape ({package: {slug, package_type}}),
        # but we tolerate a flat {slug, package_type} too. Constituent packages
        # are always fetched from `{origin}/api/packages/{slug}`.
        seen_pack: set[str] = set()
        for it in (data.get("items") or []):
            if not isinstance(it, dict):
                continue
            pkg = it.get("package") if isinstance(it.get("package"), dict) else it
            p_slug = pkg.get("slug") or pkg.get("key", "")
            p_type = pkg.get("package_type") or pkg.get("type", "")
            if not p_slug or p_slug in seen_pack:
                continue
            seen_pack.add(p_slug)
            if p_type not in VALID_TYPES:
                dep_failed.append({"slug": p_slug, "reason": f"invalid type: {p_type or 'unknown'}"})
                continue

            p_url = f"{origin}/api/packages/{p_slug}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as pc:
                    pr = await pc.get(p_url, headers=headers)
                pr.raise_for_status()
                p_data = pr.json()
            except httpx.HTTPStatusError as exc:
                dep_failed.append({"slug": p_slug, "type": p_type, "reason": f"HTTP {exc.response.status_code}"})
                continue
            except Exception as exc:
                logger.warning("[marketplace] failed to fetch pack item %s: %s", p_slug, exc)
                dep_failed.append({"slug": p_slug, "type": p_type, "reason": "fetch failed"})
                continue

            try:
                if p_type == "agent":
                    reason = await _create_agent_row(p_data, org_id, db)
                    if reason is None:
                        ai, ask, af = await _install_agent_deps(p_data, p_url, headers, org_id, db)
                        dep_installed.extend(ai)
                        dep_skipped.extend(ask)
                        dep_failed.extend(af)
                else:
                    reason = await _install_dependency_package(p_type, p_data, org_id, db)
            except Exception as exc:
                logger.warning("[marketplace] failed to install pack item %s: %s", p_slug, exc)
                dep_failed.append({"slug": p_slug, "type": p_type, "reason": str(exc)})
                continue

            if reason is None:
                await record_install(db, org_id, p_type, p_data, origin)
                dep_installed.append({"slug": p_slug, "type": p_type})
            else:
                dep_skipped.append({"slug": p_slug, "type": p_type, "reason": reason})

    # Try to increment install_count on the local marketplace item if it exists
    r = await db.execute(select(MarketplaceItem).where(MarketplaceItem.slug == slug, MarketplaceItem.is_active == True))
    local_item = r.scalar_one_or_none()
    if local_item:
        local_item.install_count += 1

    # Newly-written seed files must be discoverable: bust the loader cache so the
    # imported skill/tool/persona/agent (and any pack contents) appear immediately
    # without a restart.
    try:
        from src.seeds.loader import reload as _reload_seeds
        _reload_seeds()
    except Exception:
        pass

    await db.commit()
    response: dict = {
        "installed": True,
        "slug": slug,
        "type": item_type,
        "name": name,
        # GitLab #158 — third-party liability surface for the calling UI/CLI.
        "disclaimer": disclaimer,
        "warning_level": risk["warning_level"],
        "trust_tier": risk["trust_tier"],
        "risk_acknowledged": risk_record["acknowledged"],
    }
    if item_type in ("agent", "pack"):
        response["installed_dependencies"] = dep_installed
        response["skipped_dependencies"] = dep_skipped
        response["failed_dependencies"] = dep_failed
        if dep_note:
            response["dependencies_note"] = dep_note

    # Surface any Python requirements just written to disk (this item + any
    # installed deps) so the UI can prompt to provision the per-pack venv.
    try:
        from src.services import tool_envs
        from src.services.agent_tools.tool_subprocess import find_seed_dir
        keys = {slug}
        for d in dep_installed:
            if d.get("slug"):
                keys.add(d["slug"])
        pending: list[dict] = []
        seen_hashes: set[str] = set()
        for k in keys:
            sd = find_seed_dir(k)
            if not sd:
                continue
            reqs = tool_envs.read_requirements(sd)
            if not reqs:
                continue
            st = tool_envs.status(reqs)
            if st["env_hash"] in seen_hashes:
                continue
            seen_hashes.add(st["env_hash"])
            pending.append(st)
        if pending:
            response["python_requirements"] = pending
    except Exception as exc:  # noqa: BLE001 — never fail an import over this
        logger.debug("[marketplace] requirements scan failed: %s", exc)

    # Surface the env vars (API keys/secrets) the imported tools declare so the UI
    # can prompt for any not yet configured at org/user scope (modal after deps).
    try:
        from src.services import env_vars as _env_vars
        from src.services.agent_tools.tool_subprocess import find_seed_dir
        _env_vars.reload_env_keys()  # freshly-written seeds may declare env_vars
        ekeys = {slug}
        for d in dep_installed:
            if d.get("slug"):
                ekeys.add(d["slug"])
        required: dict[str, list[str]] = {}
        for k in ekeys:
            if not find_seed_dir(k):
                continue
            for ev in _env_vars.tool_env_keys(k):
                required.setdefault(ev, []).append(k)
        if required:
            response["required_env_vars"] = [
                {"key": ev, "tools": sorted(set(tools))} for ev, tools in sorted(required.items())
            ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("[marketplace] env_vars scan failed: %s", exc)

    return response


# ── Update detection + apply ────────────────────────────────────────────────
def _installed_to_dict(ip: InstalledPackage) -> dict:
    return {
        "id": ip.id,
        "item_type": ip.item_type,
        "source_slug": ip.source_slug,
        "origin": ip.origin,
        "name": ip.name,
        "installed_version": ip.installed_version,
        "available_version": ip.available_version,
        "pricing_type": ip.pricing_type,
        "update_available": bool(ip.available_version),
        "trust_tier": ip.trust_tier,
        "warning_level": ip.warning_level,
        "risk_acknowledged": ip.risk_acknowledged,
        "risk_acknowledged_at": ip.risk_acknowledged_at.isoformat() if ip.risk_acknowledged_at else None,
        "last_checked_at": ip.last_checked_at.isoformat() if ip.last_checked_at else None,
    }


@router.get("/updates")
async def list_updates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Installed marketplace items for the active org with their update status.
    `update_available` is set by the last check (POST /marketplace/updates/check)."""
    org_id = await get_active_org_id(current_user, db)
    rows = (await db.execute(
        select(InstalledPackage).where(InstalledPackage.org_id == org_id)
        .order_by(InstalledPackage.name)
    )).scalars().all()
    items = [_installed_to_dict(r) for r in rows]
    return {"items": items, "updates_available": sum(1 for i in items if i["update_available"])}


@router.post("/updates/check")
async def check_for_updates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poll each source marketplace for current versions and refresh update status."""
    from src.services.marketplace_updates import check_updates
    org_id = await get_active_org_id(current_user, db)
    headers = _marketplace_headers(current_user)
    updated = await check_updates(db, org_id, headers)
    return {"checked": True, "updates_available": len(updated),
            "items": [_installed_to_dict(r) for r in updated]}


async def _check_entitlement(origin: str, slug: str, headers: dict) -> bool:
    """Paid-item gate: ask the source marketplace whether the caller still owns
    this package (purchase / active sub / valid license-bundled). Fails OPEN only
    on transport error — a definitive `entitled:false` blocks the update."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{origin.rstrip('/')}/api/payments/packages/{slug}/entitlement", headers=headers
            )
        if resp.status_code == 200:
            return bool(resp.json().get("entitled"))
        # Endpoint missing / payments disabled on that marketplace → don't block.
        return True
    except Exception:  # noqa: BLE001
        return True


@router.post("/updates/{installed_id}/apply", status_code=status.HTTP_200_OK)
async def apply_update(
    installed_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-fetch an installed item from its source marketplace and overwrite the
    local seed + definition with the latest version. For paid items, re-checks
    entitlement first (402 if no longer entitled)."""
    org_id = await get_active_org_id(current_user, db)
    ip = (await db.execute(
        select(InstalledPackage).where(
            InstalledPackage.id == installed_id, InstalledPackage.org_id == org_id
        )
    )).scalar_one_or_none()
    if not ip:
        raise HTTPException(status_code=404, detail="Installed package not found")

    headers = _marketplace_headers(current_user)

    # Paid-item entitlement gate (Phase 2).
    if (ip.pricing_type or "free") != "free":
        if not await _check_entitlement(ip.origin, ip.source_slug, headers):
            raise HTTPException(
                status_code=402,
                detail="Update requires a valid purchase/entitlement for this paid package.",
            )

    # Re-fetch the package definition from its source marketplace.
    url = f"{ip.origin.rstrip('/')}/api/packages/{ip.source_slug}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Marketplace returned {exc.response.status_code}")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch update from marketplace")

    manifest = data.get("manifest") or {}
    files = data.get("files") or {}
    name = data.get("name", ip.name)
    description = data.get("description", "")

    # Overwrite the on-disk seed (the runnable definition) + refresh the DB row's
    # behavioral fields where the type carries them.
    if ip.item_type == "skill":
        write_custom_seed("skill", ip.source_slug, files, manifest)
        row = (await db.execute(select(Skill).where(Skill.org_id == org_id, Skill.key == ip.source_slug))).scalar_one_or_none()
        if row:
            row.name, row.description = name, description
    elif ip.item_type == "tool":
        write_custom_seed("tool", ip.source_slug, files, manifest)
        row = (await db.execute(select(Tool).where(Tool.org_id == org_id, Tool.key == ip.source_slug))).scalar_one_or_none()
        if row:
            row.name, row.description = name, description
    elif ip.item_type == "persona":
        key = ip.source_slug.lower().replace(" ", "_")
        write_custom_seed("persona", key, files, manifest)
        row = (await db.execute(select(Persona).where(Persona.org_id == org_id, Persona.key == key))).scalar_one_or_none()
        if row:
            row.name = name
            row.description = description
            row.icon = manifest.get("icon") or data.get("icon") or row.icon
            row.soul = manifest.get("soul") or data.get("soul") or row.soul
            row.system_prompt = manifest.get("system_prompt") or data.get("system_prompt") or row.system_prompt
            row.default_skills = manifest.get("default_skills") or data.get("default_skills") or row.default_skills
            row.default_tools = manifest.get("default_tools") or data.get("default_tools") or row.default_tools
            row.default_mcps = manifest.get("default_mcps") or data.get("default_mcps") or row.default_mcps
    elif ip.item_type == "agent":
        key = _agent_seed_key(ip.source_slug, manifest.get("name") or name)
        write_custom_seed("agent", key, files, manifest)
        agent_name = manifest.get("name") or name
        row = (await db.execute(select(Agent).where(Agent.org_id == org_id, Agent.name == agent_name))).scalar_one_or_none()

        def _m(field, default):
            v = manifest.get(field)
            if v is None:
                v = data.get(field)
            return default if v is None else v
        if row:
            row.description = description or manifest.get("description") or row.description
            row.soul = _m("soul", row.soul)
            row.system_prompt = _m("system_prompt", row.system_prompt)
            row.skills = _m("skills", row.skills)
            row.tools = _m("tools", row.tools)
            row.mcps = _m("mcps", row.mcps)
            row.temperature = _m("temperature", row.temperature)
            row.max_tokens = _m("max_tokens", row.max_tokens)

    # Bump provenance to the new version + clear the update flag.
    await record_install(db, org_id, ip.item_type, data, ip.origin)

    try:
        from src.seeds.loader import reload as _reload_seeds
        _reload_seeds()
    except Exception:
        pass

    await db.commit()
    return {"updated": True, "slug": ip.source_slug, "type": ip.item_type,
            "version": str(data.get("version") or ip.installed_version)}


@router.post("/registry/{slug}/buy")
async def buy_registry_package(
    slug: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Proxy a buy request to the external marketplace — returns a Stripe checkout_url
    (or already_owned:true). The caller opens the URL in a new tab."""
    from src.core.config import get_settings
    base = get_settings().nexora_marketplace_url.rstrip("/")
    headers = _marketplace_headers(current_user)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{base}/api/payments/packages/{slug}/buy", headers=headers)
        if resp.status_code in (200, 201):
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Buy request failed"))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to reach marketplace payments")


@router.delete("/installed/{slug}", status_code=status.HTTP_200_OK)
async def uninstall_package(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Uninstall a marketplace package from the active org.

    Removes the DB row (Skill/Tool/Persona/Agent), the InstalledPackage provenance
    record, and the on-disk custom seed directory. Built-in seeds are not deleted
    from disk (only the org DB row is removed so the org no longer has it active)."""
    from src.api.routers.seeds import _CUSTOM_ROOTS
    org_id = await get_active_org_id(current_user, db)

    # Resolve via InstalledPackage so we know the type.
    ip = (await db.execute(
        select(InstalledPackage).where(
            InstalledPackage.org_id == org_id,
            InstalledPackage.source_slug == slug,
        )
    )).scalar_one_or_none()

    item_type: str | None = ip.item_type if ip else None

    # If not in InstalledPackage, try to infer type from DB rows.
    if not item_type:
        if (await db.execute(select(Skill.id).where(Skill.org_id == org_id, Skill.key == slug))).first():
            item_type = "skill"
        elif (await db.execute(select(Tool.id).where(Tool.org_id == org_id, Tool.key == slug))).first():
            item_type = "tool"
        elif (await db.execute(select(Persona.id).where(Persona.org_id == org_id, Persona.key == slug))).first():
            item_type = "persona"

    if not item_type:
        raise HTTPException(status_code=404, detail="Package not installed")

    # Remove org DB row.
    if item_type == "skill":
        row = (await db.execute(select(Skill).where(Skill.org_id == org_id, Skill.key == slug, Skill.is_builtin == False))).scalar_one_or_none()  # noqa: E712
        if row:
            await db.delete(row)
    elif item_type == "tool":
        row = (await db.execute(select(Tool).where(Tool.org_id == org_id, Tool.key == slug))).scalar_one_or_none()
        if row:
            await db.delete(row)
    elif item_type == "persona":
        key = slug.lower().replace(" ", "_")
        row = (await db.execute(select(Persona).where(Persona.org_id == org_id, Persona.key == key))).scalar_one_or_none()
        if row:
            await db.delete(row)
    elif item_type == "agent":
        row = (await db.execute(select(Agent).where(Agent.org_id == org_id, Agent.marketplace_slug == slug))).scalar_one_or_none()
        if not row:
            row = (await db.execute(select(Agent).where(Agent.org_id == org_id, Agent.name == slug))).scalar_one_or_none()
        if row:
            await db.delete(row)

    # Remove InstalledPackage record.
    if ip:
        await db.delete(ip)

    # Delete custom seed dir if it exists (non-builtin packages only).
    seed_dir = _CUSTOM_ROOTS.get(item_type)
    if seed_dir:
        target = (seed_dir / slug).resolve()
        if target.exists() and target.is_relative_to(seed_dir):
            shutil.rmtree(target, ignore_errors=True)

    try:
        from src.seeds.loader import reload as _reload_seeds
        _reload_seeds()
    except Exception:
        pass

    await db.commit()
    return {"uninstalled": True, "slug": slug, "type": item_type}


@router.get("/{slug}")
async def get_marketplace_item(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.execute(select(MarketplaceItem).where(MarketplaceItem.slug == slug, MarketplaceItem.is_active == True))
    item = r.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return _item_to_dict(item)


@router.post("/{slug}/install", status_code=status.HTTP_201_CREATED)
async def install_marketplace_item(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Install a marketplace item to the current org.

    Builtin items are always available — install simply marks them active for the org.
    For skills/tools: creates an org-scoped DB record pointing at the builtin seed.
    """
    org_id = await get_active_org_id(current_user, db)

    r = await db.execute(select(MarketplaceItem).where(MarketplaceItem.slug == slug, MarketplaceItem.is_active == True))
    item = r.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.item_type == "skill":
        existing = await db.execute(select(Skill).where(Skill.org_id == org_id, Skill.key == slug))
        if not existing.scalar_one_or_none():
            from src.seeds.loader import get_skill
            seed = get_skill(slug) or {}
            db.add(Skill(
                id=str(_uuid.uuid4()),
                org_id=org_id,
                key=slug,
                name=item.name,
                description=item.description,
                category=seed.get("category", "community"),
                is_builtin=False,
            ))

    elif item.item_type == "tool":
        existing = await db.execute(select(Tool).where(Tool.org_id == org_id, Tool.key == slug))
        if not existing.scalar_one_or_none():
            from src.seeds.loader import get_tool
            seed = get_tool(slug) or {}
            db.add(Tool(
                id=str(_uuid.uuid4()),
                org_id=org_id,
                key=slug,
                name=item.name,
                description=item.description,
                category=seed.get("category", "community"),
            ))

    # Increment install counter
    item.install_count += 1
    await db.commit()

    return {"installed": True, "slug": slug, "type": item.item_type, "name": item.name}
