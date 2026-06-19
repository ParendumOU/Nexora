"""Bulk-import git repositories as Nexora projects."""
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.git_credential import GitCredential
from src.models.project import Project
from src.services.git_repo_browser import fetch_repos_for_credential

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
        return {"error": "credential_id is required"}

    # repos: explicit list [{full_name, name?, description?, default_branch?}]
    # OR groups: ["group-name"] to import all repos from matching groups
    # OR import_all: true to import everything
    repos_arg: list[dict] = args.get("repos") or []
    groups_filter: list[str] = [g.lower() for g in (args.get("groups") or [])]
    import_all: bool = bool(args.get("import_all", False))
    skip_if_exists: bool = bool(args.get("skip_if_exists", True))

    if not repos_arg and not groups_filter and not import_all:
        return {"error": "Provide repos list, groups filter, or import_all=true"}

    async with AsyncSessionLocal() as db:
        cr = await db.execute(
            select(GitCredential).where(
                GitCredential.id == credential_id,
                GitCredential.org_id == org_id,
            )
        )
        cred = cr.scalar_one_or_none()
        if not cred:
            return {"error": f"Credential {credential_id!r} not found in this org"}

    try:
        all_repos = await fetch_repos_for_credential(cred)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"Failed to fetch repositories: {exc}"}

    # Build index for explicit repo matching
    if repos_arg:
        full_name_index = {r["full_name"].lower(): r for r in all_repos}
        name_index = {r["name"].lower(): r for r in all_repos}
        selected: list[dict] = []
        for req in repos_arg:
            fn = (req.get("full_name") or "").lower()
            nm = (req.get("name") or "").lower()
            matched = full_name_index.get(fn) or name_index.get(nm)
            if matched:
                # allow caller to override name/description
                merged = dict(matched)
                if req.get("name"):
                    merged["name"] = req["name"]
                if req.get("description") is not None:
                    merged["description"] = req["description"]
                if req.get("default_branch"):
                    merged["default_branch"] = req["default_branch"]
                selected.append(merged)
    elif groups_filter:
        selected = [
            r for r in all_repos
            if any(gf in (r.get("group") or "").lower() for gf in groups_filter)
        ]
    else:
        selected = all_repos

    if not selected:
        return {"data": {"created": [], "skipped": [], "errors": [], "message": "No matching repositories found"}}

    created_list = []
    skipped_list = []
    error_list = []

    async with AsyncSessionLocal() as db:
        # Pre-load existing project names for this org to batch skip checks
        existing_r = await db.execute(
            select(Project.name).where(Project.org_id == org_id, Project.status != "deleted")
        )
        existing_names = {row[0] for row in existing_r.all()}

        for repo in selected:
            project_name = repo["name"]
            if project_name in existing_names:
                if skip_if_exists:
                    skipped_list.append({"name": project_name, "reason": "name_exists"})
                    continue
                else:
                    error_list.append({"name": project_name, "error": "Project already exists"})
                    continue

            meta: dict = {"repo_credential_id": credential_id}
            if repo.get("default_branch"):
                meta["repo_branch"] = repo["default_branch"]
            if repo.get("is_private") is not None:
                meta["is_private"] = repo["is_private"]

            pm_agent = Agent(
                id=str(uuid.uuid4()),
                org_id=org_id,
                name=f"{project_name} — Project Manager",
                agent_type="project_manager",
                description=f"Automatic PM for project: {project_name}",
                soul=DEFAULT_PM_SOUL,
                system_prompt=DEFAULT_PM_PROMPT,
                skills=["task_decompose", "agent_spawn", "summarize"],
            )
            project = Project(
                id=str(uuid.uuid4()),
                org_id=org_id,
                name=project_name,
                description=repo.get("description") or None,
                repo_url=repo["web_url"],
                repo_type=cred.provider,
                pm_agent_id=pm_agent.id,
                tools=[],
                mcps=[],
                env_vars={},
                meta=meta,
            )
            db.add(pm_agent)
            db.add(project)
            existing_names.add(project_name)
            created_list.append({
                "id": project.id,
                "name": project_name,
                "repo_url": repo["web_url"],
                "full_name": repo.get("full_name"),
            })

        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            return {"error": f"Database error during import: {exc}"}

    # Fire Telegram topic creation for each new project
    try:
        import asyncio
        from src.services.telegram.sync import create_project_topic as _tg
        for p in created_list:
            asyncio.create_task(_tg(p["id"], p["name"], org_id))
    except Exception:
        pass

    from src.core.pubsub import broadcast
    await broadcast(f"org:{org_id}:chats", {
        "type": "projects_imported",
        "count": len(created_list),
    })

    return {
        "data": {
            "created": created_list,
            "skipped": skipped_list,
            "errors": error_list,
            "summary": {
                "created_count": len(created_list),
                "skipped_count": len(skipped_list),
                "error_count": len(error_list),
                "total_considered": len(selected),
            },
        }
    }
