from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.models.user import User
from src.models.chat import Chat
from src.models.project import Project
from src.models.org import OrgMember


async def _can_access_chat(user_id: str, chat: Chat, db: AsyncSession) -> bool:
    """Return True if user_id can read this chat.

    Walks up the parent_chat_id chain so sub-chats (created by sub-agents)
    inherit access from their root — e.g. a Telegram vchat's sub-chats are
    accessible to any org member that can access the root vchat.
    """
    from src.api.access import _access_via_single_chat
    visited: set[str] = set()
    current: Chat | None = chat
    while current and current.id not in visited:
        visited.add(current.id)
        if await _access_via_single_chat(current, user_id, db):
            return True
        if not current.parent_chat_id:
            break
        r = await db.execute(select(Chat).where(Chat.id == current.parent_chat_id))
        current = r.scalar_one_or_none()
    return False


async def _get_active_org_project_ids(user: User, db: AsyncSession) -> set[str]:
    active_org_id = user.active_org_id
    if not active_org_id:
        r = await db.execute(select(OrgMember).where(OrgMember.user_id == user.id).limit(1))
        m = r.scalar_one_or_none()
        active_org_id = m.org_id if m else None
    if not active_org_id:
        return set()
    r = await db.execute(select(Project.id).where(Project.org_id == active_org_id))
    return {row[0] for row in r.all()}
