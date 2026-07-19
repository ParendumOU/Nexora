"""Dispatch external events (git webhooks, etc.) to a project's PM agent as tasks."""
import asyncio
import logging
import uuid

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.task import Task

logger = logging.getLogger(__name__)


async def dispatch_event_to_agent(
    org_id: str,
    project_id: str | None,
    agent_id: str,
    event_title: str,
    event_description: str,
) -> str | None:
    """Create a chat + task for a git event and dispatch to the PM agent.

    Returns the task_id, or None if the agent was not found.
    """
    from src.seeding.seed_platform import SYSTEM_USER_ID

    async with AsyncSessionLocal() as db:
        ra = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = ra.scalar_one_or_none()
        if not agent:
            logger.warning(f"[event_dispatcher] agent {agent_id} not found, skipping")
            return None
        max_concurrency = agent.max_concurrency or 2

        task_id = str(uuid.uuid4())

        # Reuse one host chat per (agent, project) event stream — webhook storms
        # previously minted a fresh top-level chat per event, unbounded. Each event
        # is still its own Task (own sub-chat / kanban card) inside that stream.
        from src.core.config import get_settings as _gs
        host_title = f"[Events] {agent.name}"
        chat_id: str | None = None
        if _gs().event_reuse_host_chat:
            prev_r = await db.execute(
                select(Chat).where(
                    Chat.user_id == SYSTEM_USER_ID,
                    Chat.agent_id == agent_id,
                    (Chat.project_id == project_id) if project_id else Chat.project_id.is_(None),
                    Chat.title == host_title,
                    Chat.is_archived.is_(False),
                    Chat.parent_chat_id.is_(None),
                ).order_by(Chat.updated_at.desc()).limit(1)
            )
            prev_chat = prev_r.scalars().first()
            if prev_chat:
                chat_id = prev_chat.id
                from datetime import datetime, timezone
                prev_chat.updated_at = datetime.now(timezone.utc)

        if chat_id is None:
            chat_id = str(uuid.uuid4())
            chat = Chat(
                id=chat_id,
                user_id=SYSTEM_USER_ID,
                agent_id=agent_id,
                project_id=project_id,
                title=host_title if _gs().event_reuse_host_chat else event_title,
            )
            db.add(chat)
            await db.flush()

        task = Task(
            id=task_id,
            org_id=org_id,
            chat_id=chat_id,
            title=event_title,
            description=event_description,
            assigned_agent_id=agent_id,
            status="pending",
        )
        db.add(task)
        await db.commit()

    asyncio.create_task(
        _dispatch_and_finish(task_id, chat_id, org_id, project_id, agent_id, max_concurrency)
    )
    logger.info(f"[event_dispatcher] queued '{event_title}' → agent {agent_id} (task {task_id})")
    return task_id


async def _dispatch_and_finish(
    task_id: str,
    chat_id: str,
    org_id: str,
    project_id: str | None,
    agent_id: str,
    max_concurrency: int,
) -> None:
    from src.services.sub_agent import _execute_sub_agent_task
    from src.services.task_dispatcher import dispatch as _dispatch
    from src.seeding.seed_platform import SYSTEM_USER_ID

    try:
        await _dispatch(
            task_id=task_id,
            org_id=org_id,
            coro_factory=lambda: _execute_sub_agent_task(
                task_id=task_id,
                parent_chat_id=chat_id,
                org_id=org_id,
                parent_chat_project_id=project_id,
                parent_chat_provider_chain_id=None,
                user_id=SYSTEM_USER_ID,
            ),
            agent_id=agent_id,
            agent_max_concurrency=max_concurrency,
        )
    except Exception as exc:
        logger.error(f"[event_dispatcher] dispatch failed for task {task_id}: {exc}", exc_info=True)
