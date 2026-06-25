import json
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.agent_log import AgentLog
from src.core.pubsub import broadcast


async def _resolve_root_chat_notes(db, chat_id: str) -> str:
    """Walk parent_chat_id chain to find root chat notes."""
    visited: set[str] = set()
    current_id = chat_id
    while current_id and current_id not in visited:
        visited.add(current_id)
        r = await db.execute(select(Chat).where(Chat.id == current_id))
        chat = r.scalar_one_or_none()
        if not chat or not chat.parent_chat_id:
            return chat.notes or "" if chat else ""
        current_id = chat.parent_chat_id
    return ""


def _build_system_prompt(base: str | None, context_seed: dict) -> str | None:
    """Merge context_seed fields into the agent system prompt."""
    parts: list[str] = []
    if base:
        parts.append(base)
    summary = (context_seed.get("inject_context_summary") or "").strip()
    if summary:
        parts.append(f"## Context from Parent Agent\n\n{summary}")
    task = (context_seed.get("initial_task") or "").strip()
    if task:
        parts.append(f"## Initial Assignment\n\n{task}")
    return "\n\n".join(parts) if parts else None


async def _resolve_org(agent_id, chat_id) -> str | None:
    """Resolve the org for the new agent. Tries, in order: the calling agent's org,
    the chat-agent's org, the chat's project org, then the chat user's active org.
    The user fallback matters when the chat runs on a builtin/seed agent that has no
    org-scoped DB row (the old version returned None there and create failed)."""
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

    agent_name_arg = args.get("name")
    if not agent_name_arg:
        return {"error": "Missing required field: name"}

    context_seed = args.get("context_seed") or {}

    async with AsyncSessionLocal() as db:
        # Resolve project notes if caller requested inheritance
        project_notes = ""
        if context_seed.get("inherit_project_notes"):
            project_notes = await _resolve_root_chat_notes(db, chat_id)

        if project_notes:
            context_seed = dict(context_seed)
            existing_summary = (context_seed.get("inject_context_summary") or "").strip()
            notes_block = f"### Shared Project Notes\n\n{project_notes}"
            context_seed["inject_context_summary"] = (
                f"{existing_summary}\n\n{notes_block}".strip() if existing_summary else notes_block
            )

        system_prompt = _build_system_prompt(args.get("system_prompt"), context_seed)

        # Per-license agent quota (no-op in OSS).
        from src.services.billing_limits import agent_quota_message
        _q = await agent_quota_message(org_id)
        if _q:
            return {"error": _q}

        new_agent = Agent(
            id=str(uuid.uuid4()), org_id=org_id, name=agent_name_arg,
            agent_type=args.get("agent_type", "custom"),
            description=args.get("description"),
            soul=args.get("soul", {}),
            system_prompt=system_prompt,
            skills=args.get("skills", []),
            tools=args.get("tools", []),
            temperature=args.get("temperature", 0.3),
            max_tokens=str(args.get("max_tokens", 8192)),
            env_vars=args.get("env_vars", {}),
            mcps=args.get("mcps", []),
            is_active=True,
        )
        db.add(new_agent)
        await db.commit()
        await db.refresh(new_agent)
        result = {
            "id": new_agent.id, "name": new_agent.name,
            "agent_type": new_agent.agent_type, "description": new_agent.description,
            "skills": new_agent.skills or [], "tools": new_agent.tools or [],
        }

        summary = json.dumps(result)[:300]
        entry = AgentLog(
            id=str(uuid.uuid4()), chat_id=chat_id, agent_id=agent_id,
            agent_name=agent_name, level="info",
            message=f"platform_create_agent: {summary}",
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
