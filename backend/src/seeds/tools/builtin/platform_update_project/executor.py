"""Patch a Nexora project."""
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
            # user → org membership fallback
            if chat and chat.user_id:
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


_TOP_FIELDS = {
    "name", "description", "repo_url", "repo_type", "provider_chain_id",
    "pm_agent_id", "status", "tools", "mcps", "env_vars",
}
_META_FIELDS = {"repo_branch", "repo_credential_id", "is_private"}


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    project_id = args.get("project_id")
    if not project_id:
        return {"error": "project_id is required"}

    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id"}

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Project).where(Project.id == project_id))
        project = r.unique().scalar_one_or_none()
        if not project:
            return {"error": f"Project {project_id} not found"}
        if project.org_id != org_id:
            return {"error": "Project belongs to a different org"}

        updated: list[str] = []
        for f in _TOP_FIELDS:
            if f in args and args[f] is not None:
                setattr(project, f, args[f])
                updated.append(f)
        if any(f in args for f in _META_FIELDS):
            meta = dict(project.meta or {})
            for f in _META_FIELDS:
                if f in args and args[f] is not None:
                    meta[f] = args[f]
                    updated.append(f)
            project.meta = meta

        if not updated:
            return {"error": "No updatable fields provided"}

        await db.commit()
        await db.refresh(project)
        result = {
            "id": project.id, "name": project.name,
            "repo_url": project.repo_url,
            "updated_fields": updated,
        }

    await broadcast(f"org:{org_id}:chats", {"type": "project_updated", "project": result})
    return {"data": result}
