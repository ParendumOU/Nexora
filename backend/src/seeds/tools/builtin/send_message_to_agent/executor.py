"""In-process executor for send_message_to_agent — peer-to-peer agent message bus."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.task import Task
from src.models.agent_message import AgentMessage

logger = logging.getLogger(__name__)

_REPLY_TIMEOUT = 120  # seconds
_CHAIN_TTL = 300  # Redis TTL for escalation chain key


def _escalation_max_depth() -> int:
    from src.core.config import get_settings
    return get_settings().max_subdelegation_depth + 1


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict | None:
    to_agent_id = args.get("to_agent_id", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    reply_to_id = args.get("reply_to_id")
    mode = args.get("mode", "sync")

    if not to_agent_id:
        return {"error": "to_agent_id is required"}
    if not subject or not body:
        return {"error": "subject and body are required"}

    async with AsyncSessionLocal() as db:
        from_agent = None
        org_id = None
        if agent_id:
            r = await db.execute(select(Agent).where(Agent.id == agent_id))
            from_agent = r.scalar_one_or_none()
            if from_agent:
                org_id = from_agent.org_id

        # Find root chat for task placement and user context
        r2 = await db.execute(select(Chat).where(Chat.id == chat_id))
        sub_chat = r2.scalar_one_or_none()
        parent_chat_id = sub_chat.parent_chat_id if (sub_chat and sub_chat.parent_chat_id) else chat_id

        r3 = await db.execute(select(Chat).where(Chat.id == parent_chat_id))
        parent_chat = r3.scalar_one_or_none()
        if not parent_chat:
            return {"error": "Could not resolve parent chat"}

        parent_chat_project_id = parent_chat.project_id
        parent_chat_provider_chain_id = parent_chat.provider_chain_id
        user_id = parent_chat.user_id

        if not org_id and parent_chat.agent_id:
            r_orch = await db.execute(select(Agent).where(Agent.id == parent_chat.agent_id))
            orch = r_orch.scalar_one_or_none()
            if orch:
                org_id = orch.org_id

        # Validate recipient
        r4 = await db.execute(select(Agent).where(Agent.id == to_agent_id))
        to_agent = r4.scalar_one_or_none()
        if not to_agent:
            return {"error": f"Agent '{to_agent_id}' not found"}
        if to_agent.org_id != org_id:
            return {"error": "Cannot message agent from a different org"}
        if not to_agent.is_active:
            return {"error": f"Agent '{to_agent.name}' is not active"}
        if to_agent_id == agent_id:
            return {"error": "Cannot send a message to yourself"}

        # Handle reply: update original message and unblock the sender
        if reply_to_id:
            r5 = await db.execute(select(AgentMessage).where(AgentMessage.id == reply_to_id))
            original = r5.scalar_one_or_none()
            if not original:
                return {"error": f"Original message '{reply_to_id}' not found"}
            if original.status in ("pending", "delivered"):
                original.status = "replied"
                original.reply_body = body
                original.replied_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info(f"[send_message_to_agent] replied to message {reply_to_id}")
                return {"data": {"status": "reply_sent", "original_message_id": reply_to_id}}
            return {"error": f"Message '{reply_to_id}' already in state '{original.status}'"}

    # Deadlock detection via Redis escalation chain
    from src.core.redis import get_redis
    redis = get_redis()
    chain_key = f"escalation_chain:{parent_chat_id}"
    chain_bytes = await redis.smembers(chain_key)
    chain = {b.decode() if isinstance(b, bytes) else b for b in chain_bytes}

    if len(chain) >= _escalation_max_depth():
        return {"error": f"Max escalation depth ({_escalation_max_depth()}) reached — deadlock prevention"}
    if to_agent_id in chain:
        return {"error": f"Cycle detected: agent '{to_agent.name}' is already in the escalation chain"}

    await redis.sadd(chain_key, agent_id or "unknown")
    await redis.expire(chain_key, _CHAIN_TTL)

    # Persist message and create recipient task in a single transaction
    msg_id = str(uuid.uuid4())
    task_id_for_msg: str | None = None

    async with AsyncSessionLocal() as db:
        msg = AgentMessage(
            id=msg_id,
            from_agent_id=agent_id or "",
            to_agent_id=to_agent_id,
            chat_id=parent_chat_id,
            subject=subject,
            body=body,
            mode=mode,
            status="delivered",
            delivered_at=datetime.now(timezone.utc),
        )
        db.add(msg)
        await db.flush()

        from_name = from_agent.name if from_agent else (agent_name or agent_id or "Agent")
        task_obj = Task(
            id=str(uuid.uuid4()),
            org_id=org_id,
            chat_id=parent_chat_id,
            title=f"[Message from {from_name}] {subject}",
            description=(
                f"**From:** {from_name}\n"
                f"**Message ID:** {msg_id}\n\n"
                f"{body}\n\n"
                "---\n"
                f"Reply using `send_message_to_agent` with `reply_to_id: \"{msg_id}\"` "
                f"and `to_agent_id: \"{agent_id or ''}\"`"
            ),
            assigned_agent_id=to_agent_id,
            status="pending",
        )
        db.add(task_obj)
        await db.commit()
        task_id_for_msg = task_obj.id
        msg.task_id = task_id_for_msg
        await db.commit()

    logger.info(
        f"[send_message_to_agent] {from_name} → {to_agent.name}: "
        f"msg={msg_id} task={task_id_for_msg} mode={mode}"
    )

    # Dispatch through the rate-limited queue (respects max_subagents + per-org semaphore).
    from src.services.sub_agent import _run_delegated_tasks
    asyncio.create_task(_run_delegated_tasks(parent_chat_id, org_id, user_id))

    if mode == "async":
        return {"data": {
            "message_id": msg_id,
            "task_id": task_id_for_msg,
            "status": "dispatched",
        }}

    # Blocking wait: poll DB for reply up to _REPLY_TIMEOUT seconds
    for _ in range(_REPLY_TIMEOUT):
        await asyncio.sleep(1)
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(AgentMessage).where(AgentMessage.id == msg_id))
            m = r.scalar_one_or_none()
            if m and m.status == "replied":
                logger.info(f"[send_message_to_agent] reply received for {msg_id}")
                return {"data": {
                    "message_id": msg_id,
                    "status": "replied",
                    "reply": m.reply_body,
                }}
            if m and m.status == "timeout":
                return {"error": "Message timed out — no reply received"}

    # Mark as timed out
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(AgentMessage).where(AgentMessage.id == msg_id))
        m = r.scalar_one_or_none()
        if m and m.status not in ("replied",):
            m.status = "timeout"
            await db.commit()

    return {"error": f"No reply received within {_REPLY_TIMEOUT}s — message timed out"}
