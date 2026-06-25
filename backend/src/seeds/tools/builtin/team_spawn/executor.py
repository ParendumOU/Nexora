"""In-process executor for the team_spawn tool.

Called from tool_calls fences:
    {
      "name": "team_spawn",
      "args": {
        "team_name": "Feature Team Alpha",
        "members": [
          {"persona_key": "developer", "count": 3},
          {"persona_key": "qa_engineer", "count": 1},
          {"persona_key": "devops", "count": 1}
        ]
      }
    }
"""
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.agent_log import AgentLog
from src.core.pubsub import broadcast
from src.services.team_spawner import MemberSpec, spawn_team


async def _resolve_org(agent_id: str | None, chat_id: str) -> str | None:
    # Robust chain (agent → chat parent walk → root user org) so a builtin/seed
    # orchestrator or a sub-chat still resolves its org.
    from src.services.org_resolve import resolve_chat_org
    async with AsyncSessionLocal() as db:
        return await resolve_chat_org(db, chat_id, agent_id)


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict | None:
    raw_members = args.get("members")
    if not raw_members or not isinstance(raw_members, list):
        return {"error": "Missing or invalid 'members' list"}

    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id"}

    from src.seeds.loader import get_all_personas
    valid_keys = {p["key"] for p in get_all_personas()}

    specs: list[MemberSpec] = []
    for m in raw_members:
        if not isinstance(m, dict):
            return {"error": f"Each member must be an object, got: {m!r}"}
        key = m.get("persona_key")
        if not key:
            return {"error": "Each member must have a 'persona_key'"}
        if key not in valid_keys:
            return {"error": f"Unknown persona_key {key!r}. Valid keys: {sorted(valid_keys)}"}
        specs.append(MemberSpec(
            persona_key=key,
            count=int(m.get("count", 1)),
            name_prefix=m.get("name_prefix"),
            overrides=m.get("overrides") or {},
        ))

    result = await spawn_team(
        org_id=org_id,
        members=specs,
        team_name=args.get("team_name"),
    )

    data = {
        "team_name": result.team_name,
        "total": result.total,
        "agents": result.agents,
    }

    summary = f"Spawned team: {result.total} agent(s) created"
    if result.team_name:
        summary = f"{result.team_name}: {result.total} agent(s) created"

    async with AsyncSessionLocal() as db:
        entry = AgentLog(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            agent_id=agent_id,
            agent_name=agent_name,
            level="info",
            message=f"team_spawn: {summary}",
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

    return {"data": data}
