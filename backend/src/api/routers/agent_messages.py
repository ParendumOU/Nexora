"""Agent messages router — read inter-agent messages for a chat."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.core.database import get_db
from src.models.agent_message import AgentMessage
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent-messages", tags=["agent-messages"])


def _msg_dict(m: AgentMessage, from_name: str | None, to_name: str | None) -> dict:
    return {
        "id": m.id,
        "from_agent_id": m.from_agent_id,
        "from_agent_name": from_name,
        "to_agent_id": m.to_agent_id,
        "to_agent_name": to_name,
        "chat_id": m.chat_id,
        "task_id": m.task_id,
        "subject": m.subject,
        "body": m.body,
        "reply_to_id": m.reply_to_id,
        "reply_body": m.reply_body,
        "status": m.status,
        "mode": m.mode,
        "created_at": m.created_at.isoformat(),
        "delivered_at": m.delivered_at.isoformat() if m.delivered_at else None,
        "replied_at": m.replied_at.isoformat() if m.replied_at else None,
    }


@router.get("/chat/{chat_id}")
async def list_chat_messages(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify chat belongs to org
    r = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = r.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    r2 = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.chat_id == chat_id)
        .order_by(AgentMessage.created_at)
    )
    messages = r2.scalars().all()

    # Batch-resolve agent names
    agent_ids = {m.from_agent_id for m in messages} | {m.to_agent_id for m in messages}
    name_map: dict[str, str] = {}
    if agent_ids:
        r3 = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        for aid, aname in r3.all():
            name_map[aid] = aname

    return [_msg_dict(m, name_map.get(m.from_agent_id), name_map.get(m.to_agent_id)) for m in messages]
