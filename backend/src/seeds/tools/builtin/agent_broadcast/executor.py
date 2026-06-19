"""agent_broadcast — fan-out async message from one agent to many."""
import asyncio
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
        return {"error": "agent_broadcast requires an agent context — assign an agent to this chat first."}

    subject = (args.get("subject") or "").strip()
    body = (args.get("body") or "").strip()
    if not subject or not body:
        return {"error": "subject and body are required"}

    channel: str | None = args.get("channel")
    explicit_ids: list[str] = args.get("agent_ids") or []

    async with AsyncSessionLocal() as db:
        # Resolve sender and org
        r = await db.execute(select(Agent).where(Agent.id == agent_id))
        from_agent = r.scalar_one_or_none()
        if not from_agent:
            return {"error": f"Sender agent {agent_id} not found"}
        org_id = from_agent.org_id
        from_name = from_agent.name or agent_name or agent_id

        # Resolve parent chat context
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

        # Resolve recipient agents
        if explicit_ids:
            q = select(Agent).where(Agent.id.in_(explicit_ids), Agent.org_id == org_id, Agent.is_active == True)  # noqa: E712
        elif channel:
            # Channel: agents whose soul.subscribed_channels contains this channel
            q = select(Agent).where(Agent.org_id == org_id, Agent.is_active == True)  # noqa: E712
        else:
            # Broadcast to all active agents in org
            q = select(Agent).where(Agent.org_id == org_id, Agent.is_active == True)  # noqa: E712

        result = await db.execute(q)
        all_agents = result.scalars().all()

        # Filter: exclude self; apply channel filter in-process
        recipients = []
        for ag in all_agents:
            if ag.id == agent_id:
                continue
            if channel:
                soul = ag.soul or {}
                subscribed = soul.get("subscribed_channels") or []
                if channel not in subscribed:
                    continue
            recipients.append(ag)

        if not recipients:
            scope = f"channel {channel!r}" if channel else ("explicit list" if explicit_ids else "all agents")
            return {"data": {
                "dispatched": 0,
                "skipped": 0,
                "reason": f"No eligible recipients in {scope}",
            }}

        # Create messages + tasks for all recipients
        dispatched: list[dict] = []
        tasks_to_dispatch: list[tuple[str, str]] = []  # (task_id, to_agent_id)

        now = datetime.now(timezone.utc)
        for recipient in recipients:
            msg_id = str(uuid.uuid4())
            task_id = str(uuid.uuid4())

            channel_prefix = f"[{channel}] " if channel else ""
            msg = AgentMessage(
                id=msg_id,
                from_agent_id=agent_id,
                to_agent_id=recipient.id,
                chat_id=parent_chat_id,
                subject=f"{channel_prefix}{subject}",
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
                title=f"[Broadcast from {from_name}] {channel_prefix}{subject}",
                description=(
                    f"**From:** {from_name}"
                    + (f"  **Channel:** {channel}" if channel else "")
                    + f"\n**Message ID:** {msg_id}\n\n{body}\n\n---\n"
                    f"Reply (optional): `send_message_to_agent` with "
                    f'`reply_to_id: "{msg_id}"` and `to_agent_id: "{agent_id}"`'
                ),
                assigned_agent_id=recipient.id,
                status="pending",
            )
            db.add(task_obj)
            dispatched.append({"to_agent_id": recipient.id, "to_agent_name": recipient.name, "message_id": msg_id, "task_id": task_id})
            tasks_to_dispatch.append((task_id, recipient.id))

        await db.commit()

        # Update task_ids on messages
        for i, (task_id, _) in enumerate(tasks_to_dispatch):
            msg_id = dispatched[i]["message_id"]
            r_msg = await db.execute(select(AgentMessage).where(AgentMessage.id == msg_id))
            m = r_msg.scalar_one_or_none()
            if m:
                m.task_id = task_id
        await db.commit()

    logger.info(
        f"[agent_broadcast] {from_name} → {len(dispatched)} agents "
        + (f"channel={channel!r}" if channel else "(all)")
    )

    # Dispatch through the rate-limited queue — respects max_subagents cap,
    # tasks_per_batch, and the Redis per-org concurrency semaphore.
    # Direct _execute_sub_agent_task calls would bypass all concurrency controls.
    from src.services.sub_agent import _run_delegated_tasks
    asyncio.create_task(_run_delegated_tasks(parent_chat_id, org_id, user_id))

    return {"data": {
        "dispatched": len(dispatched),
        "channel": channel,
        "recipients": dispatched,
    }}
