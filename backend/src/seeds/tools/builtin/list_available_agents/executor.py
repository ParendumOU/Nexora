"""In-process executor for list_available_agents — org agent discovery."""
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict | None:
    org_id = None
    chat_orchestrator_id = None
    async with AsyncSessionLocal() as db:
        if agent_id:
            r = await db.execute(select(Agent).where(Agent.id == agent_id))
            ag = r.scalar_one_or_none()
            if ag:
                org_id = ag.org_id

        r2 = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat_rec = r2.scalar_one_or_none()
        if chat_rec and chat_rec.agent_id:
            chat_orchestrator_id = chat_rec.agent_id
            if not org_id:
                r3 = await db.execute(select(Agent).where(Agent.id == chat_rec.agent_id))
                orch = r3.scalar_one_or_none()
                if orch:
                    org_id = orch.org_id

        if not org_id:
            return {"error": "Could not resolve org_id"}

        r4 = await db.execute(
            select(Agent).where(Agent.org_id == org_id, Agent.is_active == True)  # noqa: E712
        )
        agents = r4.scalars().all()

    result = [
        {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "agent_type": a.agent_type,
            "skills": a.skills or [],
        }
        for a in agents
        if a.id != chat_orchestrator_id
    ]

    return {"data": {"agents": result, "total": len(result)}}
