"""agent_notify — typed event notification between agents via AgentBus."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.agent_message import AgentMessage
from src.models.chat import Chat
from src.models.task import Task

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = frozenset({
    "task_completed",
    "task_failed",
    "issue_created",
    "issue_closed",
    "pr_merged",
    "pr_opened",
    "pipeline_failed",
    "pipeline_succeeded",
    "agent_blocked",
    "agent_unblocked",
    "deploy_started",
    "deploy_completed",
    "custom",
})


def _format_subject(event_type: str, payload: dict) -> str:
    templates = {
        "task_completed": "Task completed: {title}",
        "task_failed": "Task failed: {title}",
        "issue_created": "Issue created: {title}",
        "issue_closed": "Issue closed: {title}",
        "pr_merged": "PR merged: {title}",
        "pr_opened": "PR opened: {title}",
        "pipeline_failed": "Pipeline failed on {ref}",
        "pipeline_succeeded": "Pipeline succeeded on {ref}",
        "agent_blocked": "Agent blocked: {reason}",
        "agent_unblocked": "Agent unblocked",
        "deploy_started": "Deploy started: {ref}",
        "deploy_completed": "Deploy completed: {ref}",
        "custom": "{title}",
    }
    template = templates.get(event_type, "{event_type} event")
    try:
        return template.format(event_type=event_type, **{k: str(v) for k, v in payload.items()})
    except KeyError:
        return f"[{event_type}]"


async def _dispatch_message(
    from_agent_id: str, from_name: str, to_agent: Agent,
    subject: str, body: str,
    parent_chat_id: str, org_id: str,
    user_id: str | None, project_id: str | None, provider_chain_id: str | None,
    db,
) -> dict:
    msg_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    msg = AgentMessage(
        id=msg_id,
        from_agent_id=from_agent_id,
        to_agent_id=to_agent.id,
        chat_id=parent_chat_id,
        subject=subject,
        body=body,
        mode="async",
        status="delivered",
        delivered_at=now,
    )
    db.add(msg)

    task_obj = Task(
        id=task_id,
        org_id=org_id,
        chat_id=parent_chat_id,
        title=f"[Notification from {from_name}] {subject}",
        description=(
            f"**From:** {from_name}\n"
            f"**Message ID:** {msg_id}\n\n"
            f"{body}"
        ),
        assigned_agent_id=to_agent.id,
        status="pending",
    )
    db.add(task_obj)
    await db.flush()

    msg.task_id = task_id
    return {"to_agent_id": to_agent.id, "to_agent_name": to_agent.name, "message_id": msg_id, "task_id": task_id}


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    # Resolve agent_id from chat record if not provided by caller
    if not agent_id:
        from src.models.chat import Chat as _Chat
        async with AsyncSessionLocal() as _db:
            _r = await _db.execute(select(_Chat).where(_Chat.id == chat_id))
            _chat = _r.scalar_one_or_none()
            if _chat and _chat.agent_id:
                agent_id = _chat.agent_id
    if not agent_id:
        return {"error": "agent_notify requires an agent context — assign an agent to this chat first."}

    event_type = (args.get("event_type") or "custom").strip().lower()
    if event_type not in VALID_EVENT_TYPES:
        return {
            "error": f"Unknown event_type '{event_type}'. Valid: {', '.join(sorted(VALID_EVENT_TYPES))}"
        }

    payload: dict = args.get("payload") or {}
    target_agent_id: str | None = args.get("target_agent_id")
    # Optional human-readable message; falls back to auto-generated from payload
    message: str = (args.get("message") or "").strip()

    subject = _format_subject(event_type, payload)
    body = (
        f"**Event:** `{event_type}`\n\n"
        + (f"{message}\n\n" if message else "")
        + (f"**Payload:**\n```json\n{json.dumps(payload, indent=2)}\n```" if payload else "")
    ).strip()

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Agent).where(Agent.id == agent_id))
        from_agent = r.scalar_one_or_none()
        if not from_agent:
            return {"error": f"Sender agent {agent_id} not found"}
        org_id = from_agent.org_id
        from_name = from_agent.name or agent_name or agent_id

        # Resolve parent chat
        r2 = await db.execute(select(Chat).where(Chat.id == chat_id))
        sub_chat = r2.scalar_one_or_none()
        parent_chat_id = sub_chat.parent_chat_id if (sub_chat and sub_chat.parent_chat_id) else chat_id
        r3 = await db.execute(select(Chat).where(Chat.id == parent_chat_id))
        parent_chat = r3.scalar_one_or_none()
        if not parent_chat:
            return {"error": "Could not resolve parent chat"}
        user_id = parent_chat.user_id
        project_id = parent_chat.project_id
        provider_chain_id = parent_chat.provider_chain_id

        # Resolve recipients
        if target_agent_id:
            r4 = await db.execute(
                select(Agent).where(Agent.id == target_agent_id, Agent.org_id == org_id, Agent.is_active == True)  # noqa: E712
            )
            target = r4.scalar_one_or_none()
            if not target:
                return {"error": f"Target agent {target_agent_id} not found or inactive"}
            recipients = [target]
        else:
            # Fan-out to all agents subscribed to this event_type
            r4 = await db.execute(
                select(Agent).where(Agent.org_id == org_id, Agent.is_active == True, Agent.id != agent_id)  # noqa: E712
            )
            all_agents = r4.scalars().all()
            recipients = [
                ag for ag in all_agents
                if event_type in ((ag.soul or {}).get("subscribed_events") or [])
            ]

        if not recipients:
            scope = f"agent {target_agent_id}" if target_agent_id else f"event subscribers for '{event_type}'"
            return {"data": {
                "dispatched": 0,
                "reason": f"No eligible recipients ({scope}). "
                          "Agents subscribe via agent_update_self with soul.subscribed_events.",
            }}

        dispatched = []
        task_ids = []
        for recipient in recipients:
            if recipient.id == agent_id:
                continue
            result = await _dispatch_message(
                from_agent_id=agent_id, from_name=from_name,
                to_agent=recipient, subject=subject, body=body,
                parent_chat_id=parent_chat_id, org_id=org_id,
                user_id=user_id, project_id=project_id,
                provider_chain_id=provider_chain_id, db=db,
            )
            dispatched.append(result)
            task_ids.append(result["task_id"])

        await db.commit()

    logger.info(
        f"[agent_notify] {from_name} emitted '{event_type}' → {len(dispatched)} recipient(s)"
    )

    from src.services.sub_agent import _run_delegated_tasks
    asyncio.create_task(_run_delegated_tasks(parent_chat_id, org_id, user_id))

    return {"data": {
        "event_type": event_type,
        "dispatched": len(dispatched),
        "recipients": dispatched,
    }}
