"""agent_read_inbox — lets an agent read messages sent to it by other agents."""
from sqlalchemy import select, desc
from src.core.database import AsyncSessionLocal
from src.models.agent_message import AgentMessage
from src.models.agent import Agent
from src.models.chat import Chat


_BODY_MAX = 600
_REPLY_MAX = 300


def _msg_dict(m: AgentMessage, include_from_name: str | None = None) -> dict:
    body = (m.body or "")[:_BODY_MAX] + ("…" if m.body and len(m.body) > _BODY_MAX else "")
    d: dict = {
        "id": m.id,
        "from": include_from_name,
        "subject": m.subject,
        "body": body,
        "status": m.status,
    }
    if m.reply_body:
        rb = m.reply_body[:_REPLY_MAX] + ("…" if len(m.reply_body) > _REPLY_MAX else "")
        d["reply_body"] = rb
    return d


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    # Resolve agent_id from chat record if not provided by caller
    if not agent_id:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Chat).where(Chat.id == chat_id))
            chat = r.scalar_one_or_none()
            if chat and chat.agent_id:
                agent_id = chat.agent_id
    if not agent_id:
        return {"error": "agent_read_inbox requires an agent context — assign an agent to this chat first."}

    status_filter = args.get("status")  # delivered | replied | timeout | all (default: all)
    unread_only = bool(args.get("unread_only", False))
    limit = min(int(args.get("limit", 20)), 100)
    offset = int(args.get("offset", 0))

    async with AsyncSessionLocal() as db:
        q = (
            select(AgentMessage)
            .where(AgentMessage.to_agent_id == agent_id)
            .order_by(desc(AgentMessage.created_at))
        )

        if unread_only:
            q = q.where(AgentMessage.status == "delivered")
        elif status_filter and status_filter != "all":
            q = q.where(AgentMessage.status == status_filter)

        q = q.offset(offset).limit(limit)
        result = await db.execute(q)
        messages = result.scalars().all()

        # Resolve sender names in one query
        sender_ids = list({m.from_agent_id for m in messages})
        names: dict[str, str] = {}
        if sender_ids:
            r = await db.execute(select(Agent).where(Agent.id.in_(sender_ids)))
            for ag in r.scalars().all():
                names[ag.id] = ag.name

        return {"data": {
            "messages": [_msg_dict(m, names.get(m.from_agent_id)) for m in messages],
            "count": len(messages),
        }}
