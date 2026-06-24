"""Unit tests for the CLI-provider sub-agent spawn depth guard.

`spawn_subagent_task` refuses to create a new sub-agent once the chat's
ancestry depth reaches `max_subdelegation_depth`. We drive that branch by
patching `delegation_depth` and `get_settings`, and verify `delegation_depth` itself
against an in-memory chat ancestry.
"""
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models  # noqa: F401
from src.models.chat import Chat
import src.services.sub_agent.spawn as spawn


@pytest_asyncio.fixture
async def session_factory():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await eng.dispose()


# ── delegation_depth ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def testdelegation_depth_root_is_zero(session_factory):
    root_id = str(uuid.uuid4())
    async with session_factory() as db:
        db.add(Chat(id=root_id, user_id="u1", title="root", parent_chat_id=None))
        await db.commit()
    with patch.object(spawn, "AsyncSessionLocal", session_factory):
        assert await spawn.delegation_depth(root_id) == 0


@pytest.mark.asyncio
async def testdelegation_depth_counts_ancestry(session_factory):
    ids = [str(uuid.uuid4()) for _ in range(3)]
    async with session_factory() as db:
        db.add(Chat(id=ids[0], user_id="u1", title="root", parent_chat_id=None))
        db.add(Chat(id=ids[1], user_id="u1", title="child", parent_chat_id=ids[0]))
        db.add(Chat(id=ids[2], user_id="u1", title="grandchild", parent_chat_id=ids[1]))
        await db.commit()
    with patch.object(spawn, "AsyncSessionLocal", session_factory):
        assert await spawn.delegation_depth(ids[2]) == 2
        assert await spawn.delegation_depth(ids[1]) == 1


@pytest.mark.asyncio
async def testdelegation_depth_handles_cycle_safely(session_factory):
    # A self-referential / cyclic parent must not loop forever.
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    async with session_factory() as db:
        db.add(Chat(id=a, user_id="u1", title="a", parent_chat_id=b))
        db.add(Chat(id=b, user_id="u1", title="b", parent_chat_id=a))
        await db.commit()
    with patch.object(spawn, "AsyncSessionLocal", session_factory):
        depth = await spawn.delegation_depth(a)
        # Loop terminates via the `seen` set — depth is bounded, not infinite.
        assert isinstance(depth, int)
        assert depth <= 2


# ── spawn_subagent_task depth guard ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_spawn_refused_at_depth_cap():
    chat_id = str(uuid.uuid4())
    with patch.object(spawn, "delegation_depth", new=AsyncMock(return_value=4)), \
            patch("src.core.config.get_settings", return_value=SimpleNamespace(max_subdelegation_depth=4)):
        result = await spawn.spawn_subagent_task(
            {"title": "deep", "task": "do thing"}, chat_id, None, "Agent"
        )
    assert "maximum delegation depth" in result.lower()


@pytest.mark.asyncio
async def test_spawn_refused_when_over_cap():
    chat_id = str(uuid.uuid4())
    with patch.object(spawn, "delegation_depth", new=AsyncMock(return_value=9)), \
            patch("src.core.config.get_settings", return_value=SimpleNamespace(max_subdelegation_depth=4)):
        result = await spawn.spawn_subagent_task({"task": "x"}, chat_id, None, "Agent")
    assert "maximum delegation depth" in result.lower()


@pytest.mark.asyncio
async def test_spawn_allowed_below_cap_dedups(session_factory):
    """Below the cap, spawn proceeds far enough to hit the dedup query.
    We stub the DB session + tool runner so no real sub-agent is created and
    assert it returns a success/queued confirmation (not the depth refusal)."""
    chat_id = str(uuid.uuid4())

    # A session whose dedup query yields no existing duplicate task and no agent.
    class _Result:
        def scalar_one_or_none(self):
            return None

    class _FakeSession:
        async def execute(self, *_a, **_k):
            return _Result()

    @asynccontextmanager
    async def _fake_local():
        yield _FakeSession()

    with patch.object(spawn, "delegation_depth", new=AsyncMock(return_value=0)), \
            patch("src.core.config.get_settings", return_value=SimpleNamespace(max_subdelegation_depth=4)), \
            patch.object(spawn, "AsyncSessionLocal", _fake_local), \
            patch("src.services.agent_tools._run_single_tool", new=AsyncMock(return_value=None)):
        result = await spawn.spawn_subagent_task(
            {"title": "shallow", "task": "do thing"}, chat_id, None, "Agent"
        )
    assert "maximum delegation depth" not in result.lower()
    assert "sub-agent spawned" in result.lower()
