"""Periodic chat hygiene — archive finished sub-chats and idle system host chats.

Nothing is deleted: archiving sets Chat.is_archived, which removes the chat from
the sidebar and from the sub-chat reuse pool while retaining all data. Bounded,
config-driven (chat_archive_after_hours, 0 = disabled), and safe to run on any
worker (idempotent UPDATE).
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, exists, and_

from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.task import Task

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("pending", "queued", "in_progress", "paused", "blocked")


async def archive_stale_chats() -> int:
    """Archive chats that finished their work and have been idle past the cutoff.

    Two populations:
    1. Sub-chats (parent_chat_id set) with no active task attached to them and no
       activity since the cutoff. Covers delegation threads whose work concluded.
    2. System-owned top-level host chats (schedules/events, user_id = system) with
       no active task in them and no activity since the cutoff. Covers the legacy
       one-chat-per-run backlog and abandoned event streams.

    Returns the number of chats archived.
    """
    from src.core.config import get_settings
    from src.seeding.seed_platform import SYSTEM_USER_ID

    settings = get_settings()
    hours = settings.chat_archive_after_hours
    if hours <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    archived = 0
    async with AsyncSessionLocal() as db:
        # A chat is "busy" if any active task either runs inside it (sub_chat_id)
        # or lives on it (chat_id) — never archive under an in-flight task.
        def _no_active_task():
            return ~exists(
                select(Task.id).where(
                    Task.status.in_(_ACTIVE_STATUSES),
                    (Task.sub_chat_id == Chat.id) | (Task.chat_id == Chat.id),
                )
            )

        # 1. Finished, idle sub-chats.
        sub_q = (
            update(Chat)
            .where(
                Chat.parent_chat_id.isnot(None),
                Chat.is_archived.is_(False),
                Chat.updated_at < cutoff,
                _no_active_task(),
            )
            .values(is_archived=True)
            .execution_options(synchronize_session=False)
        )
        r1 = await db.execute(sub_q)
        archived += r1.rowcount or 0

        # 2. Idle system host chats (schedule/event runners). Only system-owned
        # top-level chats — user conversations are never touched.
        host_q = (
            update(Chat)
            .where(
                Chat.parent_chat_id.is_(None),
                Chat.user_id == SYSTEM_USER_ID,
                Chat.is_archived.is_(False),
                Chat.updated_at < cutoff,
                _no_active_task(),
            )
            .values(is_archived=True)
            .execution_options(synchronize_session=False)
        )
        r2 = await db.execute(host_q)
        archived += r2.rowcount or 0

        await db.commit()

    if archived:
        logger.info(f"[chat_maintenance] archived {archived} stale chat(s)")
    return archived
