import json
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.persona import Persona
from src.models.agent_log import AgentLog
from src.core.pubsub import broadcast


async def _resolve_org(agent_id, chat_id) -> str | None:
    async with AsyncSessionLocal() as db:
        if agent_id:
            r = await db.execute(select(Agent).where(Agent.id == agent_id))
            ag = r.scalar_one_or_none()
            if ag:
                return ag.org_id
        r2 = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat_rec = r2.scalar_one_or_none()
        if chat_rec and chat_rec.agent_id:
            r3 = await db.execute(select(Agent).where(Agent.id == chat_rec.agent_id))
            ag2 = r3.scalar_one_or_none()
            if ag2:
                return ag2.org_id
    return None


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id for creation"}

    key = (args.get("key") or "").lower().replace(" ", "_")
    if not key:
        return {"error": "Missing required field: key"}
    persona_name = args.get("name") or key.replace("_", " ").title()

    async with AsyncSessionLocal() as db:
        persona = Persona(
            id=str(uuid.uuid4()), org_id=org_id, key=key, name=persona_name,
            description=args.get("description"), icon=args.get("icon"),
            soul=args.get("soul", {}), system_prompt=args.get("system_prompt"),
            default_skills=args.get("default_skills", []),
            default_tools=args.get("default_tools", []),
            default_mcps=args.get("default_mcps", []),
        )
        db.add(persona)
        await db.commit()
        await db.refresh(persona)
        result = {"id": persona.id, "key": persona.key, "name": persona.name}

        summary = json.dumps(result)[:300]
        entry = AgentLog(
            id=str(uuid.uuid4()), chat_id=chat_id, agent_id=agent_id,
            agent_name=agent_name, level="info",
            message=f"platform_create_persona: {summary}",
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
