"""List projects for the current org."""
from sqlalchemy import select, or_, func as sqlfunc
from src.core.database import AsyncSessionLocal
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


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id"}

    status = (args.get("status") or "active").lower()
    search = args.get("search")

    async with AsyncSessionLocal() as db:
        stmt = select(Project).where(Project.org_id == org_id)
        if status != "all":
            stmt = stmt.where(Project.status == status)
        if search:
            pat = f"%{search.lower()}%"
            stmt = stmt.where(or_(
                sqlfunc.lower(Project.name).like(pat),
                sqlfunc.lower(Project.repo_url).like(pat),
            ))
        stmt = stmt.order_by(Project.name).limit(500)
        r = await db.execute(stmt)
        rows = r.unique().scalars().all()
        items = [{
            "id": p.id, "name": p.name, "description": p.description,
            "repo_url": p.repo_url, "repo_type": p.repo_type,
            "status": p.status, "pm_agent_id": p.pm_agent_id,
            "is_private": (p.meta or {}).get("is_private", False),
        } for p in rows]
    return {"data": {"projects": items, "count": len(items)}}
