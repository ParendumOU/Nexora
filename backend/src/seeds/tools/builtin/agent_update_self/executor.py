"""agent_update_self — lets an agent modify its own configuration at runtime."""
import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.agent_log import AgentLog
from src.models.chat import Chat
from src.core.pubsub import broadcast

logger = logging.getLogger(__name__)

# Fields an agent can freely update on itself
_FREE_FIELDS = {"description", "temperature", "max_tokens", "model_pref"}


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    # Resolve agent_id from chat record if not provided by caller
    if not agent_id:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Chat).where(Chat.id == chat_id))
            chat = r.scalar_one_or_none()
            if chat and chat.agent_id:
                agent_id = chat.agent_id
    if not agent_id:
        return {"error": "agent_update_self requires an agent context — assign an agent to this chat first."}

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = r.scalar_one_or_none()
        if not agent:
            return {"error": f"Agent {agent_id} not found"}

        changes: dict[str, object] = {}

        # system_prompt_append: add a block to the existing prompt
        append = (args.get("system_prompt_append") or "").strip()
        if append:
            existing = (agent.system_prompt or "").rstrip()
            agent.system_prompt = f"{existing}\n\n{append}".lstrip() if existing else append
            changes["system_prompt_append"] = f"{len(append)} chars"

        # system_prompt_replace: full replacement (use with care)
        if "system_prompt_replace" in args:
            agent.system_prompt = args["system_prompt_replace"]
            changes["system_prompt_replace"] = True

        # soul: merge provided keys into existing soul dict
        if "soul" in args and isinstance(args["soul"], dict):
            agent.soul = {**(agent.soul or {}), **args["soul"]}
            changes["soul"] = list(args["soul"].keys())

        # Free scalar fields
        for field in _FREE_FIELDS:
            if field in args:
                setattr(agent, field, args[field])
                changes[field] = args[field]

        # skills_add / skills_remove
        if args.get("skills_add") or args.get("skills_remove"):
            current_skills: list[str] = list(agent.skills or [])
            for s in (args.get("skills_add") or []):
                if isinstance(s, str) and s not in current_skills:
                    current_skills.append(s)
            for s in (args.get("skills_remove") or []):
                if s in current_skills:
                    current_skills.remove(s)
            agent.skills = current_skills
            changes["skills"] = current_skills

        # tools_add / tools_remove
        # Security gate: agents can only add always_allowed tools to themselves.
        # They can remove any tool (removing access is always safe).
        if args.get("tools_add") or args.get("tools_remove"):
            from src.services.agent_tools.tool_permissions import _always_allowed
            _permitted = _always_allowed()
            current_tools: list[str] = list(agent.tools or [])
            denied: list[str] = []
            for t in (args.get("tools_add") or []):
                if not isinstance(t, str):
                    continue
                if t not in _permitted:
                    denied.append(t)
                    continue
                if t not in current_tools:
                    current_tools.append(t)
            for t in (args.get("tools_remove") or []):
                if t in current_tools:
                    current_tools.remove(t)
            agent.tools = current_tools
            changes["tools"] = current_tools
            if denied:
                changes["tools_add_denied"] = denied
                logger.warning(
                    f"[agent_update_self] Agent {agent_id} attempted to add "
                    f"restricted tools (denied): {denied}"
                )

        if not changes:
            return {"data": {"updated": False, "reason": "No changes provided"}}

        await db.commit()
        await db.refresh(agent)

        # Audit log
        entry = AgentLog(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            agent_id=agent_id,
            agent_name=agent_name,
            level="info",
            message=f"agent_update_self: {list(changes.keys())}",
        )
        db.add(entry)
        await db.commit()

    await broadcast(chat_id, {"type": "log_entry", "log": {
        "id": entry.id, "chat_id": entry.chat_id, "task_id": None,
        "agent_id": entry.agent_id, "agent_name": entry.agent_name,
        "level": entry.level, "message": entry.message, "data": None,
        "created_at": entry.created_at.isoformat(),
    }})

    result = {
        "updated": True,
        "agent_id": agent_id,
        "changes": changes,
    }
    if changes.get("tools_add_denied"):
        result["warning"] = (
            "Some tools were denied — agents may only self-add always_allowed tools. "
            "Ask the orchestrator to grant restricted tools."
        )

    return {"data": result}
