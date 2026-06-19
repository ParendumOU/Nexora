"""List repositories accessible via a stored git credential."""
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.git_credential import GitCredential
from src.models.project import Project
from src.services.git_repo_browser import fetch_repos_for_credential


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
                rom = await db.execute(
                    select(OrgMember).where(OrgMember.user_id == chat.user_id).limit(1)
                )
                om = rom.scalar_one_or_none()
                if om:
                    return om.org_id
    return None


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id"}

    credential_id = (args.get("credential_id") or "").strip()
    if not credential_id:
        return {"error": "credential_id is required — use platform_list_credentials to find one"}

    group_filter = (args.get("group") or "").strip().lower()
    visibility = (args.get("visibility") or "").strip().lower()  # "public" | "private" | ""

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(GitCredential).where(
                GitCredential.id == credential_id,
                GitCredential.org_id == org_id,
            )
        )
        cred = r.scalar_one_or_none()
        if not cred:
            return {"error": f"Credential {credential_id!r} not found in this org"}

    try:
        repos = await fetch_repos_for_credential(cred)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"Failed to fetch repositories: {exc}"}

    if group_filter:
        repos = [
            r for r in repos
            if group_filter in (r.get("group") or "").lower()
            or group_filter in (r.get("full_name") or "").lower()
        ]
    if visibility == "public":
        repos = [r for r in repos if not r.get("is_private")]
    elif visibility == "private":
        repos = [r for r in repos if r.get("is_private")]

    return {
        "data": {
            "credential_id": credential_id,
            "provider": cred.provider,
            "repos": repos,
            "count": len(repos),
        }
    }
