import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.project import Project
from src.models.agent import Agent
from src.models.org import OrgMember
from src.models.chat import Chat
from src.models.task import Task
from src.models.agent_log import AgentLog
from src.models.issue import Issue

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    repo_url: str | None = None
    repo_type: str | None = None
    provider_chain_id: str | None = None


class BulkImportItem(BaseModel):
    name: str
    repo_url: str
    repo_type: str
    credential_id: str | None = None
    description: str | None = None
    default_branch: str = "main"


class BulkImportRequest(BaseModel):
    repos: list[BulkImportItem]


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    repo_url: str | None = None
    repo_type: str | None = None
    repo_branch: str | None = None
    repo_credential_id: str | None = None
    is_private: bool | None = None
    tools: list | None = None
    mcps: list | None = None
    env_vars: dict | None = None


DEFAULT_PM_SOUL = {
    "personality": "organized, strategic, clear communicator",
    "expertise": ["project management", "task decomposition", "team coordination"],
    "communication_style": "structured, uses bullet points and clear headings",
}

DEFAULT_PM_PROMPT = """You are a Project Manager AI. Your role is to:
1. Analyze incoming tasks and break them down into clear subtasks
2. Delegate subtasks to the appropriate specialist agents
3. Monitor progress and aggregate results
4. Communicate clearly and concisely with the user

When given a complex task, first decompose it, then coordinate execution.
Always respond with clear status updates as work progresses."""


def _coerce(project: Project) -> None:
    """Ensure JSON columns are never None after ALTER TABLE addition."""
    if project.tools is None:
        project.tools = []
    if project.mcps is None:
        project.mcps = []
    if project.env_vars is None:
        project.env_vars = {}


async def _enrich_project(project: Project, db: AsyncSession) -> dict:
    _coerce(project)
    pm_agent_name = None
    if project.pm_agent_id:
        r = await db.execute(select(Agent).where(Agent.id == project.pm_agent_id))
        agent = r.scalar_one_or_none()
        if agent:
            pm_agent_name = agent.name
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "repo_url": project.repo_url,
        "repo_type": project.repo_type,
        "status": project.status,
        "pm_agent_id": project.pm_agent_id,
        "pm_agent_name": pm_agent_name,
        "provider_chain_id": project.provider_chain_id,
        "tools": project.tools,
        "mcps": project.mcps,
        "env_vars": project.env_vars,
        "repo_branch": (project.meta or {}).get("repo_branch"),
        "repo_credential_id": (project.meta or {}).get("repo_credential_id"),
        "is_private": (project.meta or {}).get("is_private", False),
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "updated_at": project.updated_at.isoformat() if project.updated_at else "",
    }


async def _get_project_chat_ids(project_id: str, db: AsyncSession) -> list[str]:
    r = await db.execute(select(Chat.id).where(Chat.project_id == project_id))
    return [c for (c,) in r.all()]


@router.get("", response_model=list[dict])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Project).where(Project.org_id == org_id, Project.status != "deleted")
    )
    projects = result.unique().scalars().all()
    return [await _enrich_project(p, db) for p in projects]


@router.post("", response_model=dict, status_code=201)
async def create_project(
    req: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)

    from src.services.billing_limits import enforce_agent_quota
    await enforce_agent_quota(org_id)

    pm_agent = Agent(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=f"{req.name} — Project Manager",
        agent_type="project_manager",
        description=f"Automatic PM for project: {req.name}",
        soul=DEFAULT_PM_SOUL,
        system_prompt=DEFAULT_PM_PROMPT,
        skills=["task_decompose", "agent_spawn", "summarize"],
        tools=["read_url", "http_request", "agent_update_self", "issue_manage", "shell_run", "web_search", "file_read", "file_write", "gitlab_api", "github_api"],
    )
    project = Project(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=req.name,
        description=req.description,
        repo_url=req.repo_url,
        repo_type=req.repo_type,
        provider_chain_id=req.provider_chain_id,
        pm_agent_id=pm_agent.id,
        tools=[],
        mcps=[],
        env_vars={},
    )
    try:
        db.add(pm_agent)
        await db.flush()
        db.add(project)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(project)

    import asyncio
    from src.services.telegram.sync import create_project_topic as _tg_create_topic
    asyncio.create_task(_tg_create_topic(project.id, project.name, org_id))

    return await _enrich_project(project, db)


@router.post("/import", response_model=list[dict], status_code=201)
async def bulk_import_projects(
    req: BulkImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-create projects from a list of repos (e.g. imported from GitHub/GitLab tree)."""
    org_id = await get_active_org_id(current_user, db)
    # Each project spawns a PM agent → counts against the org's agent quota.
    # Bulk: cap the batch to remaining slots (uncommitted rows aren't visible to
    # the billing-worker's count, so a per-row check can't be relied on here).
    from src.services.billing_limits import agent_slots_remaining
    _remaining = await agent_slots_remaining(org_id)  # None = unlimited (OSS)
    repos = req.repos if _remaining is None else req.repos[:_remaining]
    if _remaining is not None and len(repos) < len(req.repos):
        logger.warning(
            "[limits] bulk import capped %d→%d for org %s (agent limit)",
            len(req.repos), len(repos), org_id,
        )
    project_objs = []
    for item in repos:
        pm_agent = Agent(
            id=str(uuid.uuid4()),
            org_id=org_id,
            name=f"{item.name} — Project Manager",
            agent_type="project_manager",
            description=f"Automatic PM for project: {item.name}",
            soul=DEFAULT_PM_SOUL,
            system_prompt=DEFAULT_PM_PROMPT,
            skills=["task_decompose", "agent_spawn", "summarize"],
            tools=["read_url", "http_request", "agent_update_self", "issue_manage", "shell_run", "web_search", "file_read", "file_write", "gitlab_api", "github_api"],
        )
        meta: dict = {}
        if item.credential_id:
            meta["repo_credential_id"] = item.credential_id
        if item.default_branch:
            meta["repo_branch"] = item.default_branch
        project = Project(
            id=str(uuid.uuid4()),
            org_id=org_id,
            name=item.name,
            description=item.description,
            repo_url=item.repo_url,
            repo_type=item.repo_type,
            pm_agent_id=pm_agent.id,
            tools=[],
            mcps=[],
            env_vars={},
            meta=meta or None,
        )
        db.add(pm_agent)
        db.add(project)
        project_objs.append(project)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    results = []
    for project in project_objs:
        await db.refresh(project)
        results.append(await _enrich_project(project, db))

    import asyncio
    from src.services.telegram.sync import create_project_topic as _tg_create_topic
    for p in results:
        asyncio.create_task(_tg_create_topic(p["id"], p["name"], org_id))

    return results


@router.get("/{project_id}", response_model=dict)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.unique().scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return await _enrich_project(project, db)


@router.patch("/{project_id}", response_model=dict)
async def update_project(
    project_id: str,
    req: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.unique().scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    _coerce(project)
    if req.name is not None:
        project.name = req.name
    if req.description is not None:
        project.description = req.description or None
    if req.repo_url is not None:
        project.repo_url = req.repo_url or None
    if req.repo_type is not None:
        project.repo_type = req.repo_type or None
    if req.tools is not None:
        project.tools = req.tools
    if req.mcps is not None:
        project.mcps = req.mcps
    if req.env_vars is not None:
        project.env_vars = req.env_vars
    # Store repo extras in meta JSON
    if any(v is not None for v in [req.repo_branch, req.repo_credential_id, req.is_private]):
        meta = dict(project.meta or {})
        if req.repo_branch is not None:
            meta["repo_branch"] = req.repo_branch
        if req.repo_credential_id is not None:
            meta["repo_credential_id"] = req.repo_credential_id
        if req.is_private is not None:
            meta["is_private"] = req.is_private
        project.meta = meta

    await db.commit()
    await db.refresh(project)
    return await _enrich_project(project, db)


@router.get("/{project_id}/agents", response_model=list[dict])
async def get_project_agents(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the PM agent + any agents assigned to tasks in this project."""
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = r.unique().scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    agent_ids: set[str] = set()
    if project.pm_agent_id:
        agent_ids.add(project.pm_agent_id)

    # Collect agents assigned to tasks in this project's chats
    chat_ids = await _get_project_chat_ids(project_id, db)
    if chat_ids:
        task_r = await db.execute(
            select(Task.assigned_agent_id)
            .where(Task.chat_id.in_(chat_ids), Task.assigned_agent_id.isnot(None))
        )
        for (aid,) in task_r.all():
            agent_ids.add(aid)

    if not agent_ids:
        return []

    agents_r = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
    agents = agents_r.scalars().all()

    result = []
    for a in agents:
        task_count = 0
        if chat_ids:
            tc_r = await db.execute(
                select(Task).where(
                    Task.chat_id.in_(chat_ids),
                    Task.assigned_agent_id == a.id,
                )
            )
            task_count = len(tc_r.scalars().all())
        result.append({
            "id": a.id,
            "name": a.name,
            "agent_type": a.agent_type,
            "description": a.description,
            "skills": a.skills or [],
            "tools": a.tools or [],
            "mcps": a.mcps or [],
            "is_pm": a.id == project.pm_agent_id,
            "task_count": task_count,
        })
    return result


@router.get("/{project_id}/tasks", response_model=list[dict])
async def get_project_tasks(
    project_id: str,
    limit: int = Query(200, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    if not r.unique().scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    chat_ids = await _get_project_chat_ids(project_id, db)
    if not chat_ids:
        return []

    task_r = await db.execute(
        select(Task)
        .where(Task.chat_id.in_(chat_ids))
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    tasks = task_r.scalars().all()

    result = []
    for t in tasks:
        agent_name = None
        if t.assigned_agent_id:
            ar = await db.execute(select(Agent).where(Agent.id == t.assigned_agent_id))
            ag = ar.scalar_one_or_none()
            if ag:
                agent_name = ag.name
        result.append({
            "id": t.id,
            "chat_id": t.chat_id,
            "parent_id": t.parent_id,
            "title": t.title,
            "description": t.description,
            "output": t.output,
            "status": t.status,
            "assigned_agent_id": t.assigned_agent_id,
            "assigned_agent_name": agent_name,
            "checklist": t.checklist or [],
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        })
    return result


@router.get("/{project_id}/logs", response_model=list[dict])
async def get_project_logs(
    project_id: str,
    limit: int = Query(200, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    if not r.unique().scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    chat_ids = await _get_project_chat_ids(project_id, db)
    if not chat_ids:
        return []

    log_r = await db.execute(
        select(AgentLog)
        .where(AgentLog.chat_id.in_(chat_ids))
        .order_by(AgentLog.created_at.desc())
        .limit(limit)
    )
    logs = log_r.scalars().all()
    return [
        {
            "id": l.id,
            "chat_id": l.chat_id,
            "task_id": l.task_id,
            "agent_id": l.agent_id,
            "agent_name": l.agent_name,
            "level": l.level,
            "message": l.message,
            "data": l.data,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


@router.get("/{project_id}/issues")
async def get_project_issues(
    project_id: str,
    status: str | None = Query(None),
    limit: int = Query(100, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    if not r.unique().scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    query = select(Issue).where(Issue.project_id == project_id)
    if status:
        statuses = [s.strip() for s in status.split(",")]
        query = query.where(Issue.status.in_(statuses))
    query = query.order_by(Issue.created_at.desc()).limit(limit)

    issue_r = await db.execute(query)
    issues = issue_r.scalars().all()
    result = []
    for i in issues:
        agent_name = None
        if i.assigned_agent_id:
            ar = await db.execute(select(Agent).where(Agent.id == i.assigned_agent_id))
            ag = ar.scalar_one_or_none()
            if ag:
                agent_name = ag.name
        result.append({
            "id": i.id,
            "title": i.title,
            "description": i.description,
            "status": i.status,
            "priority": i.priority,
            "labels": i.labels or [],
            "assigned_agent_id": i.assigned_agent_id,
            "assigned_agent_name": agent_name,
            "external_ref": i.external_ref,
            "created_at": i.created_at.isoformat(),
            "closed_at": i.closed_at.isoformat() if i.closed_at else None,
        })
    return result



@router.post("/{project_id}/sync-issues")
async def sync_project_issues(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync remote GitHub/GitLab issues into internal issue tracker."""
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    if not r.unique().scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    from src.services.git_issue_sync import sync_project_issues as _sync
    result = await _sync(project_id, db)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.unique().scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.status = "deleted"
    await db.commit()
