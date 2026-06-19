from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.project import Project
from src.models.user import User


async def _resolve_project_id(chat_rec, db) -> str | None:
    if chat_rec.project_id:
        return chat_rec.project_id
    # Try to find the user's active org and pick the first project with a repo_url
    if chat_rec.user_id:
        r = await db.execute(select(User.active_org_id).where(User.id == chat_rec.user_id))
        row = r.first()
        if row and row[0]:
            pr = await db.execute(
                select(Project.id).where(
                    Project.org_id == row[0],
                    Project.repo_url.isnot(None),
                ).limit(1)
            )
            prow = pr.first()
            if prow:
                return prow[0]
    return None


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat_rec = r.scalar_one_or_none()
        project_id = args.get("project_id")

        if not project_id and chat_rec:
            project_id = await _resolve_project_id(chat_rec, db)

        if not project_id:
            return {"error": "No project context. Provide project_id."}

        from src.services.git_issue_sync import sync_project_issues
        result = await sync_project_issues(project_id, db)

    return {"data": result}
