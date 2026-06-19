"""Create a Nexora project from inside an agent run."""
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.core.pubsub import broadcast
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.project import Project


async def _resolve_org(agent_id, chat_id) -> str | None:
    async with AsyncSessionLocal() as db:
        if agent_id:
            r = await db.execute(select(Agent).where(Agent.id == agent_id))
            ag = r.scalar_one_or_none()
            if ag:
                return ag.org_id
        r2 = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = r2.scalar_one_or_none()
        if chat:
            if chat.project_id:
                rp = await db.execute(select(Project).where(Project.id == chat.project_id))
                proj = rp.unique().scalar_one_or_none()
                if proj:
                    return proj.org_id
            if chat.agent_id:
                ra = await db.execute(select(Agent).where(Agent.id == chat.agent_id))
                ag = ra.scalar_one_or_none()
                if ag:
                    return ag.org_id
            if chat.user_id:
                from src.models.org import OrgMember
                from src.models.user import User
                ru = await db.execute(select(User).where(User.id == chat.user_id))
                u = ru.scalar_one_or_none()
                if u and u.active_org_id:
                    return u.active_org_id
                rom = await db.execute(select(OrgMember).where(OrgMember.user_id == chat.user_id).limit(1))
                om = rom.scalar_one_or_none()
                if om:
                    return om.org_id
    return None


def _infer_repo_type(repo_url: str | None) -> str | None:
    if not repo_url:
        return None
    low = repo_url.lower()
    if "gitlab" in low:
        return "gitlab"
    if "github" in low:
        return "github"
    return None


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id"}

    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}

    repo_url = (args.get("repo_url") or None)
    repo_type = args.get("repo_type") or _infer_repo_type(repo_url)
    skip_if_exists = bool(args.get("skip_if_exists", False))

    async with AsyncSessionLocal() as db:
        existing_r = await db.execute(
            select(Project).where(Project.org_id == org_id, Project.name == name).limit(1)
        )
        existing = existing_r.unique().scalar_one_or_none()
        if existing:
            if skip_if_exists:
                return {"data": {
                    "id": existing.id, "name": existing.name,
                    "repo_url": existing.repo_url,
                    "created": False,
                    "skipped_reason": "name_exists",
                }}
            return {"error": f"Project '{name}' already exists in this org (id {existing.id})"}

        meta = dict(args.get("meta") or {})
        if args.get("repo_branch"):
            meta["repo_branch"] = args["repo_branch"]
        if args.get("repo_credential_id"):
            meta["repo_credential_id"] = args["repo_credential_id"]
        if args.get("is_private") is not None:
            meta["is_private"] = bool(args["is_private"])

        new_project = Project(
            id=str(uuid.uuid4()),
            org_id=org_id,
            name=name,
            description=args.get("description"),
            repo_url=repo_url,
            repo_type=repo_type,
            provider_chain_id=args.get("provider_chain_id"),
            pm_agent_id=args.get("pm_agent_id"),
            tools=args.get("tools") or [],
            mcps=args.get("mcps") or [],
            env_vars=args.get("env_vars") or {},
            meta=meta,
        )
        db.add(new_project)
        await db.commit()
        await db.refresh(new_project)
        result = {
            "id": new_project.id, "name": new_project.name,
            "repo_url": new_project.repo_url, "repo_type": new_project.repo_type,
            "pm_agent_id": new_project.pm_agent_id,
            "created": True,
        }

    await broadcast(f"org:{org_id}:chats", {"type": "project_created", "project": result})
    return {"data": result}
