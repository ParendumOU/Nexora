from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.database import get_db
from src.api.deps import get_current_user
from src.models.user import User
from src.models.chat import Chat, Message
from src.models.agent import Agent
from src.api.routers.chats.access import _can_access_chat
from src.api.routers.chats.schemas import MessageResponse

router = APIRouter()


@router.get("/{chat_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    chat_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    result = await db.execute(
        select(Message).where(Message.chat_id == chat_id)
        .order_by(Message.created_at)
        .limit(limit)
        .offset(offset)
    )
    messages = result.scalars().all()

    agent_cache: dict[str, str | None] = {}
    user_cache: dict[str, str | None] = {}

    async def get_agent_name(agent_id: str | None) -> str | None:
        if not agent_id:
            return None
        if agent_id not in agent_cache:
            r = await db.execute(select(Agent).where(Agent.id == agent_id))
            a = r.scalar_one_or_none()
            agent_cache[agent_id] = a.name if a else None
        return agent_cache[agent_id]

    async def get_user_name(uid: str | None) -> str | None:
        if not uid:
            return None
        if uid not in user_cache:
            r = await db.execute(select(User).where(User.id == uid))
            u = r.scalar_one_or_none()
            user_cache[uid] = u.full_name if u else None
        return user_cache[uid]

    result_list = []
    for msg in messages:
        agent_name = await get_agent_name(msg.agent_id)
        # Prefer inline display name stored in metadata (e.g. Telegram messages)
        tg_display = (msg.metadata_ or {}).get("tg_user_display") if msg.metadata_ else None
        user_name = tg_display or await get_user_name(msg.user_id)
        result_list.append({
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "metadata_": msg.metadata_ or {},
            "provider_used": msg.provider_used,
            "agent_id": msg.agent_id,
            "agent_name": agent_name,
            "user_id": msg.user_id,
            "user_name": user_name,
            "excluded": msg.excluded,
            "created_at": msg.created_at,
        })

    return result_list


@router.patch("/{chat_id}/messages/{message_id}/excluded")
async def set_message_excluded(
    chat_id: str,
    message_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")
    result = await db.execute(
        select(Message).where(Message.id == message_id, Message.chat_id == chat_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.excluded = bool(body.get("excluded", False))
    await db.commit()
    return {"id": msg.id, "excluded": msg.excluded}
