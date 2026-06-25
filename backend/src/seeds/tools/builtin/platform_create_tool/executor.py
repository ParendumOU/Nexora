import json
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.tool import Tool, TOOL_CATEGORIES
from src.models.agent_log import AgentLog
from src.core.pubsub import broadcast


async def _resolve_org(agent_id, chat_id) -> str | None:
    """agent → chat-agent → chat project → chat user's active org. The user fallback
    matters when the chat runs on a builtin/seed agent with no org-scoped DB row."""
    from src.models.project import Project
    from src.models.user import User
    async with AsyncSessionLocal() as db:
        if agent_id:
            ag = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if ag and ag.org_id:
                return ag.org_id
        chat_rec = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
        if chat_rec:
            if chat_rec.agent_id:
                ag2 = (await db.execute(select(Agent).where(Agent.id == chat_rec.agent_id))).scalar_one_or_none()
                if ag2 and ag2.org_id:
                    return ag2.org_id
            if chat_rec.project_id:
                po = (await db.execute(select(Project.org_id).where(Project.id == chat_rec.project_id))).scalar_one_or_none()
                if po:
                    return po
            if chat_rec.user_id:
                uo = (await db.execute(select(User.active_org_id).where(User.id == chat_rec.user_id))).scalar_one_or_none()
                if uo:
                    return uo
    return None


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id for creation"}

    key = (args.get("key") or "").lower().replace(" ", "_")
    if not key:
        return {"error": "Missing required field: key"}
    tool_name = args.get("name") or key.replace("_", " ").title()
    category = args.get("category", "custom")
    if category not in TOOL_CATEGORIES:
        return {"error": f"Invalid category '{category}'. Choose from: {sorted(TOOL_CATEGORIES)}"}

    async with AsyncSessionLocal() as db:
        tool = Tool(
            id=str(uuid.uuid4()), org_id=org_id, key=key, name=tool_name,
            description=args.get("description"), category=category, files={},
        )
        db.add(tool)
        await db.commit()
        await db.refresh(tool)
        result = {"id": tool.id, "key": tool.key, "name": tool.name,
                  "description": tool.description, "category": tool.category}

        summary = json.dumps(result)[:300]
        entry = AgentLog(
            id=str(uuid.uuid4()), chat_id=chat_id, agent_id=agent_id,
            agent_name=agent_name, level="info",
            message=f"platform_create_tool: {summary}",
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

    await broadcast(chat_id, {"type": "log_entry", "log": {
        "id": entry.id, "chat_id": entry.chat_id, "task_id": None,
        "agent_id": entry.agent_id, "agent_name": entry.agent_name,
        "level": entry.level, "message": entry.message, "data": None,
        "created_at": entry.created_at.isoformat(),
    }})
    return {"data": result}
