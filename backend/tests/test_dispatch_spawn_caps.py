"""Dispatch-level spawn-cap enforcement.

The task_create tool only PRE-CHECKS the per-root caps (count=False); the
authoritative accounting lives at the dispatch choke point
(`_execute_sub_agent_task` claim) so tasks created programmatically
(schedules, git/webhook events, autopilot, autonomy) are bounded too.
The CLI-native subchat path (`cli_observability.subchat.create_subchat`)
applies the same depth + root-cap backstops.
"""
import uuid

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models  # noqa: F401
from src.models.chat import Chat
from src.models.agent import Agent
from src.models.task import Task


class _Sentinel(Exception):
    """Raised by a patched _find_reusable_subchat to stop the pipeline right
    after the cap gate, proving control flow passed it."""


@pytest_asyncio.fixture
async def session_factory():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await eng.dispose()


async def _seed(factory):
    """Parent chat + active agent + pending task assigned to it."""
    user_id, agent_id, parent_id, task_id = (str(uuid.uuid4()) for _ in range(4))
    async with factory() as db:
        # SQLite doesn't enforce FKs here, so org/user rows are unnecessary.
        db.add(Chat(id=parent_id, user_id=user_id, title="parent"))
        db.add(Agent(id=agent_id, org_id=str(uuid.uuid4()), name="worker", is_active=True))
        db.add(Task(id=task_id, chat_id=parent_id, title="work",
                    status="pending", assigned_agent_id=agent_id))
        await db.commit()
    return user_id, agent_id, parent_id, task_id


def _patch_dispatch_env(monkeypatch, factory, events, cap_msg):
    """Wire the executor to the test DB and stub its collaborators."""
    import src.services.sub_agent.executor as ex
    monkeypatch.setattr(ex, "AsyncSessionLocal", factory)
    monkeypatch.setattr(
        "src.services.chat_cancel.is_ancestor_cancelled", AsyncMock(return_value=False)
    )

    async def _capture(channel, event):
        events.append((channel, event))
    monkeypatch.setattr("src.core.pubsub.broadcast", _capture)

    cap_calls: list[str] = []

    async def _cap(chat_id, db, *, count=True):
        cap_calls.append(chat_id)
        return cap_msg
    monkeypatch.setattr(
        "src.services.agent_tools.tool_executor._enforce_root_spawn_caps", _cap
    )

    async def _stop(*a, **kw):
        raise _Sentinel()
    monkeypatch.setattr(ex, "_find_reusable_subchat", _stop)
    return cap_calls


@pytest.mark.asyncio
async def test_dispatch_cap_fails_task_before_any_subchat(session_factory, monkeypatch):
    from src.services.sub_agent.executor import _execute_sub_agent_task

    user_id, agent_id, parent_id, task_id = await _seed(session_factory)
    events: list = []
    cap_calls = _patch_dispatch_env(
        monkeypatch, session_factory, events, cap_msg="Sub-agent limit reached: hard cap."
    )

    await _execute_sub_agent_task(
        task_id=task_id, parent_chat_id=parent_id, org_id="o",
        parent_chat_project_id=None, parent_chat_provider_chain_id=None,
        user_id=user_id,
    )

    assert cap_calls == [parent_id]
    async with session_factory() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.status == "failed"
        assert "limit reached" in (task.last_error or "")
        assert task.sub_chat_id is None
        n_chats = len((await db.execute(select(Chat))).scalars().all())
        assert n_chats == 1  # only the parent — no sub-chat was created

    types = [e.get("type") for _, e in events]
    assert "task_updated" in types
    assert any(ch == f"subagent_done:{parent_id}" for ch, _ in events)


@pytest.mark.asyncio
async def test_dispatch_skips_cap_accounting_on_retry(session_factory, monkeypatch):
    from src.services.sub_agent.executor import _execute_sub_agent_task

    user_id, agent_id, parent_id, task_id = await _seed(session_factory)
    async with session_factory() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        task.retry_count = 1  # a retry: already billed at its first dispatch
        await db.commit()

    events: list = []
    cap_calls = _patch_dispatch_env(
        monkeypatch, session_factory, events, cap_msg="Sub-agent limit reached: hard cap."
    )

    with pytest.raises(_Sentinel):
        await _execute_sub_agent_task(
            task_id=task_id, parent_chat_id=parent_id, org_id="o",
            parent_chat_project_id=None, parent_chat_provider_chain_id=None,
            user_id=user_id,
        )
    # Cap gate was skipped entirely; control flow reached the reuse lookup.
    assert cap_calls == []


@pytest.mark.asyncio
async def test_cli_subchat_respects_depth_and_root_caps(session_factory, monkeypatch):
    import src.providers.cli_observability.subchat as sc

    user_id, agent_id, parent_id, _ = await _seed(session_factory)
    monkeypatch.setattr(sc, "AsyncSessionLocal", session_factory)
    ctx = {"chat_id": parent_id, "agent_id": agent_id, "org_id": None, "agent_name": "w"}

    # Depth cap → refuse to persist.
    from src.core.config import get_settings
    monkeypatch.setattr(
        "src.services.sub_agent.spawn.delegation_depth",
        AsyncMock(return_value=get_settings().max_subdelegation_depth),
    )
    assert await sc.create_subchat(ctx, title="t", brief="b") is None

    # Root cap → refuse to persist.
    monkeypatch.setattr(
        "src.services.sub_agent.spawn.delegation_depth", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        "src.services.agent_tools.tool_executor._enforce_root_spawn_caps",
        AsyncMock(return_value="cap hit"),
    )
    assert await sc.create_subchat(ctx, title="t", brief="b") is None

    # Caps clear → persists the sub-chat + cli_native task.
    monkeypatch.setattr(
        "src.services.agent_tools.tool_executor._enforce_root_spawn_caps",
        AsyncMock(return_value=None),
    )
    created = await sc.create_subchat(ctx, title="t", brief="b")
    assert created is not None and created["sub_chat_id"]
    async with session_factory() as db:
        task = (await db.execute(
            select(Task).where(Task.id == created["task_id"])
        )).scalar_one()
        assert (task.agent_overrides or {}).get("cli_native") is True
