import uuid
import secrets
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date
from pydantic import BaseModel, Field
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.core.permissions import require_org_role
from src.models.org import OrgRole
from src.models.user import User
from src.models.agent import Agent
from src.models.agent_memory import AgentMemory, MEMORY_TYPES
from src.models.agent_version import AgentVersion
from src.models.chat import Chat, Message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])




async def _get_agent(agent_id: str, org_id: str, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _build_snapshot(agent: Agent) -> dict:
    """Serialize all config fields of an agent into a snapshot dict."""
    return {
        "name": agent.name,
        "agent_type": agent.agent_type,
        "description": agent.description,
        "soul": agent.soul or {},
        "system_prompt": agent.system_prompt,
        "skills": agent.skills or [],
        "tools": agent.tools or [],
        "mcps": agent.mcps or [],
        "env_vars": agent.env_vars or {},
        "model_pref": agent.model_pref,
        "model_profile_id": agent.model_profile_id,
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
        "max_subagents": agent.max_subagents,
        "max_concurrency": agent.max_concurrency,
        "flow_config": agent.flow_config or {},
        "is_active": agent.is_active,
    }


async def _create_version(agent: Agent, user_id: str, db: AsyncSession) -> AgentVersion:
    """Get the next version number and create an AgentVersion snapshot."""
    max_ver = await db.scalar(
        select(func.max(AgentVersion.version_number)).where(AgentVersion.agent_id == agent.id)
    )
    next_ver = (max_ver or 0) + 1
    version = AgentVersion(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        version_number=next_ver,
        snapshot=_build_snapshot(agent),
        created_by_id=user_id,
    )
    db.add(version)
    return version


async def _validate_model_profile(profile_id: str | None, org_id: str, db: AsyncSession) -> str | None:
    """Ensure a bound model profile exists and belongs to this org.

    Returns the id when valid (or None when unset); raises 404 for a missing or
    cross-org profile so an agent can't be bound to another tenant's profile.
    """
    if not profile_id:
        return None
    from src.models.model_profile import ModelProfile
    r = await db.execute(
        select(ModelProfile.id).where(
            ModelProfile.id == profile_id, ModelProfile.org_id == org_id
        )
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="model_profile_id not found in this organization")
    return profile_id


# ── Schemas ───────────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    agent_type: str = "custom"
    description: str | None = Field(None, max_length=5000)
    soul: dict = {}
    system_prompt: str | None = Field(None, max_length=50000)
    skills: list[str] = []
    tools: list[str] = []
    model_pref: str | None = Field(None, max_length=255)
    model_profile_id: str | None = Field(None, max_length=36)
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(8192, ge=1, le=200000)
    flow_config: dict = {}
    env_vars: dict = {}
    mcps: list[dict] = []
    max_subagents: int = Field(5, ge=1, le=50)
    max_concurrency: int = Field(2, ge=1, le=50)


class AgentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    soul: dict | None = None
    system_prompt: str | None = Field(None, max_length=50000)
    skills: list[str] | None = None
    tools: list[str] | None = None
    model_pref: str | None = Field(None, max_length=255)
    model_profile_id: str | None = Field(None, max_length=36)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=1, le=200000)
    flow_config: dict | None = None
    is_active: bool | None = None
    env_vars: dict | None = None
    mcps: list[dict] | None = None
    max_subagents: int | None = Field(None, ge=1, le=50)
    max_concurrency: int | None = Field(None, ge=1, le=50)


class AgentResponse(BaseModel):
    id: str
    name: str
    agent_type: str
    description: str | None = None
    soul: dict = {}
    system_prompt: str | None = None
    skills: list = []
    tools: list = []
    model_pref: str | None = None
    model_profile_id: str | None = None
    temperature: float = 0.3
    flow_config: dict = {}
    is_active: bool = True
    is_builtin: bool = False
    env_vars: dict = {}
    mcps: list = []
    max_subagents: int = 5
    max_concurrency: int = 2

    model_config = {"from_attributes": True}

    def model_post_init(self, __context: object) -> None:
        # Coerce NULL DB values to empty collections
        if self.soul is None: self.soul = {}
        if self.skills is None: self.skills = []
        if self.tools is None: self.tools = []
        if self.env_vars is None: self.env_vars = {}
        if self.mcps is None: self.mcps = []
        if self.flow_config is None: self.flow_config = {}


class MemoryCreate(BaseModel):
    type: str = "fact"
    content: str
    tags: list[str] = []
    priority: int = 3


class MemoryUpdate(BaseModel):
    type: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    priority: int | None = None


class MemoryResponse(BaseModel):
    id: str
    agent_id: str
    type: str
    content: str
    tags: list
    priority: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


def _memory_dict(m: AgentMemory) -> dict:
    return {
        "id": m.id,
        "agent_id": m.agent_id,
        "type": m.type,
        "content": m.content,
        "tags": m.tags or [],
        "priority": m.priority,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
    }


# ── Static routes first (must precede /{agent_id}) ───────────────────────────

@router.get("/builtin/{key}/files")
async def get_builtin_agent_files(
    key: str,
    current_user: User = Depends(get_current_user),
):
    try:
        from src.seeds.loader import get_all_agents
        agents = get_all_agents()
    except Exception:
        agents = []

    agent_data = next(
        (a for a in agents if a.get("_source") == "builtin" and Path(a.get("_dir", "")).name == key),
        None,
    )
    if not agent_data:
        raise HTTPException(status_code=404, detail="Builtin agent not found")

    agent_dir = Path(agent_data["_dir"])
    files: dict[str, str] = {}
    for f in sorted(agent_dir.iterdir()):
        if f.is_file():
            try:
                files[f.name] = f.read_text(encoding="utf-8")
            except Exception:
                files[f.name] = ""

    return {"files": files, "key": key, "name": agent_data.get("name", "")}


@router.get("/types/builtin")
async def get_builtin_types():
    from src.seeds.loader import get_all_personas
    personas = get_all_personas()
    types = []
    for p in personas:
        types.append({
            "type": p.get("key"),
            "label": p.get("name"),
            "description": p.get("description"),
            "icon": p.get("icon", "sparkles"),
            "default_skills": p.get("default_skills", []),
        })
    return {"types": types}


# Category mapping keyed by agent_type / agent dir name
_TEMPLATE_CATEGORIES: dict[str, str] = {
    "project_manager": "Productivity",
    "scrum_master": "Productivity",
    "agent_architect": "DevOps",
    "infrastructure_manager": "DevOps",
    "persona_architect": "DevOps",
    "skill_architect": "DevOps",
    "tool_architect": "DevOps",
    "code": "Code",
    "developer": "Code",
    "qa_engineer": "Code",
    "support": "Customer Support",
    "customer_support": "Customer Support",
    "research": "Research",
    "researcher": "Research",
}


def _agent_category(agent: dict) -> str:
    """Derive a template category from agent data."""
    agent_type = agent.get("agent_type", "")
    dir_key = Path(agent.get("_dir", "")).name
    return (
        _TEMPLATE_CATEGORIES.get(agent_type)
        or _TEMPLATE_CATEGORIES.get(dir_key)
        or "Productivity"
    )


@router.get("/templates")
async def list_agent_templates():
    """Return builtin agent seeds as template objects. No auth required."""
    try:
        from src.seeds.loader import get_all_agents
        agents = get_all_agents()
    except Exception:
        agents = []

    templates = []
    for agent in agents:
        if agent.get("_source") != "builtin":
            continue
        dir_key = Path(agent.get("_dir", "")).name
        system_prompt = agent.get("system_prompt") or ""
        templates.append({
            "id": f"builtin:{dir_key}",
            "name": agent.get("name", ""),
            "description": agent.get("description", ""),
            "category": _agent_category(agent),
            "source": "builtin",
            "agent_type": agent.get("agent_type", "custom"),
            "model_pref": agent.get("model_pref") or "",
            "system_prompt_preview": system_prompt[:200],
            "system_prompt": system_prompt,
            "tools": agent.get("tools", []),
            "skills": agent.get("skills", []),
            "soul": agent.get("soul", {}),
            "temperature": agent.get("temperature", 0.3),
        })
    return templates


# ── Collection routes ─────────────────────────────────────────────────────────

@router.get("", response_model=list[AgentResponse])
async def list_agents(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    result = await db.execute(
        select(Agent)
        .where(Agent.org_id == org_id, Agent.is_active == True)
        .order_by(Agent.name)
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    req: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    from src.services.billing_limits import enforce_agent_quota
    await enforce_agent_quota(org_id)
    agent = Agent(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=req.name,
        agent_type=req.agent_type,
        description=req.description,
        soul=req.soul,
        system_prompt=req.system_prompt,
        skills=req.skills,
        tools=req.tools,
        model_pref=req.model_pref,
        model_profile_id=await _validate_model_profile(req.model_profile_id, org_id, db),
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        flow_config=req.flow_config,
        env_vars=req.env_vars,
        mcps=req.mcps,
        max_subagents=req.max_subagents,
        max_concurrency=req.max_concurrency,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    from src.api.routers.auth import _fire_audit_event
    _fire_audit_event(org_id, "agent.created", "agent",
                      resource_id=agent.id, user_id=current_user.id)
    return agent


# ── Item routes ───────────────────────────────────────────────────────────────

@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    return await _get_agent(agent_id, org_id, db)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    req: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    agent = await _get_agent(agent_id, org_id, db)

    _updates = req.model_dump(exclude_unset=True)
    if "model_profile_id" in _updates:
        # Validate org ownership (raises 404 for a missing/cross-org profile); None clears it.
        _updates["model_profile_id"] = await _validate_model_profile(
            _updates["model_profile_id"], org_id, db
        )
    for field, value in _updates.items():
        setattr(agent, field, value)

    # Snapshot the new state as a new version
    await _create_version(agent, current_user.id, db)

    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    agent = await _get_agent(agent_id, org_id, db)
    if agent.is_builtin:
        raise HTTPException(status_code=400, detail="Built-in agents cannot be deleted")
    agent.is_active = False
    await db.commit()
    from src.api.routers.auth import _fire_audit_event
    _fire_audit_event(org_id, "agent.deleted", "agent",
                      resource_id=agent_id, user_id=current_user.id)


# ── Version history sub-resource ─────────────────────────────────────────────

class AgentVersionSummary(BaseModel):
    id: str
    version_number: int
    created_at: str
    created_by_name: str | None = None

    model_config = {"from_attributes": True}


class AgentVersionDetail(AgentVersionSummary):
    snapshot: dict


@router.get("/{agent_id}/versions", response_model=list[AgentVersionSummary])
async def list_agent_versions(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all config versions for an agent, newest first."""
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    await _get_agent(agent_id, org_id, db)  # 404 + org check

    result = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
        .limit(limit)
        .offset(offset)
    )
    versions = result.scalars().all()

    # Resolve creator names in one query
    creator_ids = list({v.created_by_id for v in versions if v.created_by_id})
    name_map: dict[str, str] = {}
    if creator_ids:
        users_result = await db.execute(select(User).where(User.id.in_(creator_ids)))
        for u in users_result.scalars().all():
            name_map[u.id] = u.full_name or u.email

    return [
        AgentVersionSummary(
            id=v.id,
            version_number=v.version_number,
            created_at=v.created_at.isoformat(),
            created_by_name=name_map.get(v.created_by_id) if v.created_by_id else None,
        )
        for v in versions
    ]


@router.get("/{agent_id}/versions/{version_id}", response_model=AgentVersionDetail)
async def get_agent_version(
    agent_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full snapshot for a specific agent version."""
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    await _get_agent(agent_id, org_id, db)

    result = await db.execute(
        select(AgentVersion).where(
            AgentVersion.id == version_id,
            AgentVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    creator_name = None
    if version.created_by_id:
        user_result = await db.execute(select(User).where(User.id == version.created_by_id))
        creator = user_result.scalar_one_or_none()
        if creator:
            creator_name = creator.full_name or creator.email

    return AgentVersionDetail(
        id=version.id,
        version_number=version.version_number,
        created_at=version.created_at.isoformat(),
        created_by_name=creator_name,
        snapshot=version.snapshot,
    )


@router.post("/{agent_id}/versions/{version_id}/revert", response_model=AgentResponse)
async def revert_agent_to_version(
    agent_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Restore an agent's config from a previous snapshot. The revert itself also creates a new version."""
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    agent = await _get_agent(agent_id, org_id, db)

    result = await db.execute(
        select(AgentVersion).where(
            AgentVersion.id == version_id,
            AgentVersion.agent_id == agent_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    snap = version.snapshot
    # Restore all config fields from the snapshot
    config_fields = [
        "name", "agent_type", "description", "soul", "system_prompt",
        "skills", "tools", "mcps", "env_vars", "model_pref", "model_profile_id",
        "temperature", "max_tokens", "max_subagents", "max_concurrency",
        "flow_config", "is_active",
    ]
    for field in config_fields:
        if field in snap:
            setattr(agent, field, snap[field])

    # Create a new version capturing the reverted state
    await _create_version(agent, current_user.id, db)

    await db.commit()
    await db.refresh(agent)
    return agent


@router.patch("/{agent_id}/restore", response_model=AgentResponse)
async def restore_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.is_active = True
    await db.commit()
    await db.refresh(agent)
    return agent


# ── Memory sub-resource ───────────────────────────────────────────────────────

@router.get("/{agent_id}/memories", response_model=list[dict])
async def list_memories(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    await _get_agent(agent_id, org_id, db)
    result = await db.execute(
        select(AgentMemory)
        .where(AgentMemory.agent_id == agent_id)
        .order_by(AgentMemory.priority.desc(), AgentMemory.created_at)
    )
    return [_memory_dict(m) for m in result.scalars().all()]


@router.post("/{agent_id}/memories", response_model=dict, status_code=201)
async def create_memory(
    agent_id: str,
    req: MemoryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    await _get_agent(agent_id, org_id, db)

    if req.type not in MEMORY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid memory type. Choose from: {sorted(MEMORY_TYPES)}")
    if not 1 <= req.priority <= 5:
        raise HTTPException(status_code=422, detail="Priority must be 1–5")

    mem = AgentMemory(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        org_id=org_id,
        type=req.type,
        content=req.content,
        tags=req.tags,
        priority=req.priority,
    )
    db.add(mem)
    await db.commit()
    await db.refresh(mem)
    return _memory_dict(mem)


@router.patch("/{agent_id}/memories/{memory_id}", response_model=dict)
async def update_memory(
    agent_id: str,
    memory_id: str,
    req: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    await _get_agent(agent_id, org_id, db)

    result = await db.execute(
        select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.agent_id == agent_id)
    )
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(mem, field, value)

    await db.commit()
    await db.refresh(mem)
    return _memory_dict(mem)


@router.delete("/{agent_id}/memories/{memory_id}", status_code=204)
async def delete_memory(
    agent_id: str,
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    await _get_agent(agent_id, org_id, db)

    result = await db.execute(
        select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.agent_id == agent_id)
    )
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")

    await db.delete(mem)
    await db.commit()


# ── Analytics sub-resource ────────────────────────────────────────────────────

# ── Share link endpoints ──────────────────────────────────────────────────────

class ShareResponse(BaseModel):
    share_token: str
    share_enabled: bool
    share_url: str


@router.post("/{agent_id}/share", response_model=ShareResponse)
async def enable_agent_share(
    agent_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a public share token for this agent and enable sharing."""
    org_id = await get_active_org_id(current_user, db)
    agent = await _get_agent(agent_id, org_id, db)

    token = secrets.token_urlsafe(32)
    agent.share_token = token
    agent.share_enabled = True
    await db.commit()
    await db.refresh(agent)

    base = str(request.base_url).rstrip("/")
    share_url = f"{base}/share/agents/{token}"
    return ShareResponse(share_token=token, share_enabled=True, share_url=share_url)


@router.delete("/{agent_id}/share", status_code=204)
async def disable_agent_share(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable sharing and clear the share token."""
    org_id = await get_active_org_id(current_user, db)
    agent = await _get_agent(agent_id, org_id, db)
    agent.share_token = None
    agent.share_enabled = False
    await db.commit()


@router.get("/{agent_id}/share", response_model=ShareResponse)
async def get_agent_share(
    agent_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current share status for this agent."""
    org_id = await get_active_org_id(current_user, db)
    agent = await _get_agent(agent_id, org_id, db)

    base = str(request.base_url).rstrip("/")
    share_url = f"{base}/share/agents/{agent.share_token}" if agent.share_token else ""
    return ShareResponse(
        share_token=agent.share_token or "",
        share_enabled=agent.share_enabled,
        share_url=share_url,
    )


# ── Analytics sub-resource ────────────────────────────────────────────────────

@router.get("/{agent_id}/analytics")
async def get_agent_analytics(
    agent_id: str,
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await _get_agent(agent_id, org_id, db)  # 404 + org check

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Daily assistant message counts within the window
    daily_rows = await db.execute(
        select(
            cast(Message.created_at, Date).label("date"),
            func.count().label("count"),
        )
        .join(Chat, Chat.id == Message.chat_id)
        .where(Chat.agent_id == agent_id)
        .where(Message.created_at >= cutoff)
        .where(Message.role == "assistant")
        .group_by(cast(Message.created_at, Date))
        .order_by(cast(Message.created_at, Date))
    )
    daily_messages = [{"date": str(r.date), "count": r.count} for r in daily_rows]

    # Total chat sessions for this agent (all time)
    total_chats = await db.scalar(
        select(func.count()).select_from(Chat).where(Chat.agent_id == agent_id)
    ) or 0

    # Total assistant messages (all time)
    total_messages = await db.scalar(
        select(func.count(Message.id))
        .join(Chat, Chat.id == Message.chat_id)
        .where(Chat.agent_id == agent_id)
        .where(Message.role == "assistant")
    ) or 0

    # Token usage — Message.tokens_used is a single int per message (combined)
    total_tokens = await db.scalar(
        select(func.sum(Message.tokens_used))
        .join(Chat, Chat.id == Message.chat_id)
        .where(Chat.agent_id == agent_id)
        .where(Message.role == "assistant")
    ) or 0

    # Error count from agent_logs (level == "error") within the window
    from src.models.agent_log import AgentLog
    error_count = await db.scalar(
        select(func.count())
        .select_from(AgentLog)
        .where(AgentLog.agent_id == agent_id)
        .where(AgentLog.level == "error")
        .where(AgentLog.created_at >= cutoff)
    ) or 0

    return {
        "agent_id": agent_id,
        "days": days,
        "total_chats": total_chats,
        "total_messages": total_messages,
        "total_tokens": total_tokens,
        "error_count": error_count,
        "daily_messages": daily_messages,
    }


# ── Public (unauthenticated) share endpoints ──────────────────────────────────

public_router = APIRouter(prefix="/public/agents", tags=["public"])


class PublicAgentResponse(BaseModel):
    name: str
    description: str | None = None
    agent_type: str
    soul: dict = {}


class PublicChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class PublicChatResponse(BaseModel):
    response: str


async def _get_shared_agent(share_token: str, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.share_token == share_token,
            Agent.share_enabled == True,  # noqa: E712
            Agent.is_active == True,  # noqa: E712
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Shared agent not found or sharing is disabled")
    return agent


@public_router.get("/{share_token}", response_model=PublicAgentResponse)
async def get_public_agent(
    share_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Return public-safe agent info (no system prompt) for a shared agent."""
    agent = await _get_shared_agent(share_token, db)
    return PublicAgentResponse(
        name=agent.name,
        description=agent.description,
        agent_type=agent.agent_type,
        soul={k: v for k, v in (agent.soul or {}).items() if k != "system_prompt"},
    )


@public_router.post("/{share_token}/chat", response_model=PublicChatResponse)
async def public_agent_chat(
    share_token: str,
    req: PublicChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send a message to a shared agent. No auth required. Rate-limited to 10/min per IP."""
    from src.core.rate_limit import rate_limit
    await rate_limit(request, f"public_chat:{share_token}", max_requests=10, window_seconds=60)

    agent = await _get_shared_agent(share_token, db)

    # Resolve providers for the agent's org
    from src.services.agent_context import get_chain_providers
    from src.providers.router import stream_response, AllProvidersExhausted
    from src.core.database import AsyncSessionLocal

    providers = await get_chain_providers(None, agent.org_id)
    if not providers:
        raise HTTPException(status_code=503, detail="No providers configured for this agent")

    # Build messages with minimal system prompt (no platform context — public safety)
    system_parts = []
    if agent.system_prompt:
        system_parts.append(agent.system_prompt)

    messages: list[dict] = []
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})
    messages.append({"role": "user", "content": req.message.strip()})

    # Stream response and collect full text
    full_response = ""
    try:
        async for chunk in stream_response(
            providers,
            messages,
            chat_id=None,
            agent_id=agent.id,
            agent_name=agent.name,
            org_id=agent.org_id,
            user_id=None,
        ):
            from src.providers.router import _METADATA_PREFIX
            if not chunk.startswith(_METADATA_PREFIX):
                full_response += chunk
    except AllProvidersExhausted as e:
        raise HTTPException(status_code=503, detail=str(e))

    return PublicChatResponse(response=full_response)
