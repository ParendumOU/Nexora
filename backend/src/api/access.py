"""Shared chat read-access helper used by tasks, logs, and other routers.

Accepts chats that the user owns directly OR can reach via:
  - ChatParticipant record
  - Project org membership
  - Parent chat chain (sub-chats inherit access from their root)
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chat import Chat, ChatParticipant
from src.models.org import OrgMember, OrgRole
from src.models.project import Project
from src.models.user import User


async def _access_via_admin(chat: Chat, user_id: str, db: AsyncSession) -> bool:
    """Grant read access when user_id is an owner/admin of an org the chat's owner
    belongs to. Covers a member's personal (project-less) chats too, so an org admin
    can open any conversation of one of their members."""
    if not chat.user_id or chat.user_id == user_id:
        return False
    admin_org_ids = {
        row[0]
        for row in (
            await db.execute(
                select(OrgMember.org_id).where(
                    OrgMember.user_id == user_id,
                    OrgMember.role.in_([OrgRole.owner, OrgRole.admin]),
                )
            )
        ).all()
    }
    if not admin_org_ids:
        return False
    r = await db.execute(
        select(OrgMember.id).where(
            OrgMember.user_id == chat.user_id,
            OrgMember.org_id.in_(admin_org_ids),
        ).limit(1)
    )
    return r.scalar_one_or_none() is not None


async def _access_via_single_chat(chat: Chat, user_id: str, db: AsyncSession) -> bool:
    """Return True if user_id has read access to this specific chat record."""
    if chat.user_id == user_id:
        return True

    # Direct participant record
    r = await db.execute(
        select(ChatParticipant).where(
            ChatParticipant.chat_id == chat.id,
            ChatParticipant.user_id == user_id,
        )
    )
    if r.scalar_one_or_none():
        return True

    # Project org membership
    if chat.project_id:
        r = await db.execute(select(Project).where(Project.id == chat.project_id))
        proj = r.unique().scalar_one_or_none()
        if proj:
            r2 = await db.execute(
                select(OrgMember).where(
                    OrgMember.org_id == proj.org_id,
                    OrgMember.user_id == user_id,
                )
            )
            if r2.scalar_one_or_none():
                return True

    # Telegram channel vchats are owned by the system user (no project), so org members
    # need access via the integration that owns the conversation.
    org_id = await _telegram_vchat_org(chat, db)
    if org_id:
        r = await db.execute(
            select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
        )
        if r.scalar_one_or_none():
            return True

    # Org owners/admins may open any conversation of one of their members.
    if await _access_via_admin(chat, user_id, db):
        return True

    return False


async def _telegram_vchat_org(chat: Chat, db: AsyncSession) -> str | None:
    """Resolve the org that owns a Telegram vchat (via its integration); None otherwise."""
    from src.services.telegram.helpers import SYSTEM_USER_ID
    if chat.user_id != SYSTEM_USER_ID:
        return None
    from src.core.redis import get_redis
    from src.models.integration import Integration
    redis = get_redis()
    raw = await redis.get(f"vchat_int:{chat.id}")
    int_id = (raw.decode() if isinstance(raw, bytes) else raw) if raw else None
    if not int_id:
        # Backfill for vchats created before the reverse map: scan the forward keys once.
        async for key in redis.scan_iter("tg_vchat:*"):
            val = await redis.get(key)
            v = (val.decode() if isinstance(val, bytes) else val) if val else None
            if v == chat.id:
                ks = key.decode() if isinstance(key, bytes) else key
                parts = ks.split(":")  # tg_vchat:{int_id}:{tg_chat_id}
                if len(parts) >= 2:
                    int_id = parts[1]
                    await redis.set(f"vchat_int:{chat.id}", int_id, ex=90 * 24 * 3600)
                break
    if not int_id:
        return None
    r = await db.execute(select(Integration).where(Integration.id == int_id))
    integ = r.scalar_one_or_none()
    return integ.org_id if integ else None


async def assert_chat_read_access(chat_id: str, user: User, db: AsyncSession) -> Chat:
    """Raise HTTP 404 if the user cannot read the chat. Returns the Chat on success.

    Sub-chats inherit access from their parent chain so agents' sub-chats
    are always reachable if the root conversation is accessible.
    """
    r = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = r.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    visited: set[str] = set()
    current: Chat | None = chat
    while current and current.id not in visited:
        visited.add(current.id)
        if await _access_via_single_chat(current, user.id, db):
            return chat  # always return the originally requested chat
        if not current.parent_chat_id:
            break
        r2 = await db.execute(select(Chat).where(Chat.id == current.parent_chat_id))
        current = r2.scalar_one_or_none()

    raise HTTPException(status_code=404, detail="Chat not found")
