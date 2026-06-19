"""List git credentials for the current org (metadata only, no token values)."""
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.git_credential import GitCredential
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


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id"}

    provider_filter = (args.get("provider") or "").lower() or None

    async with AsyncSessionLocal() as db:
        stmt = select(GitCredential).where(GitCredential.org_id == org_id)
        if provider_filter:
            stmt = stmt.where(GitCredential.provider == provider_filter)
        r = await db.execute(stmt)
        creds = r.scalars().all()
        items = [{
            "id": c.id,
            "name": c.name,
            "provider": c.provider,
            "base_url": c.base_url or (
                "https://gitlab.com" if c.provider == "gitlab" else "https://api.github.com"
            ),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        } for c in creds]
    return {"data": {"credentials": items, "count": len(items)}}
