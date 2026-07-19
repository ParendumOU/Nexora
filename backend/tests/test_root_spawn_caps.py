"""Unit tests for the per-ROOT sub-agent spawn backstop
(tool_executor._walk_chat_to_root + _enforce_root_spawn_caps).

The per-parent fan-out cap only bounds siblings under one parent; a recursive
loop evades it by spawning across many sub-chats. These caps count spawns against
the ROOT conversation (cumulative + rate, in Redis) so a runaway cannot create
unbounded sub-agents — the exact failure that produced ~227 chats once.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models  # noqa: F401
from src.models.chat import Chat
import src.services.agent_tools.tool_executor as te


@pytest_asyncio.fixture
async def db():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await eng.dispose()


class _FakeRedis:
    """Minimal async Redis stub: incr/get/expire over an in-memory dict."""
    def __init__(self):
        self.store: dict[str, int] = {}
    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]
    async def get(self, key):
        return self.store.get(key)
    async def expire(self, key, ttl):
        return True


def _patch_redis(monkeypatch, fake):
    monkeypatch.setattr("src.core.redis.get_redis", lambda: fake)


def _set_caps(monkeypatch, *, total, rate, window=60):
    from src.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "max_subagents_per_root", total, raising=False)
    monkeypatch.setattr(s, "max_spawn_rate_per_root", rate, raising=False)
    monkeypatch.setattr(s, "max_spawn_rate_window_seconds", window, raising=False)
    monkeypatch.setattr("src.core.config.get_settings", lambda: s)


# ── _walk_chat_to_root ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_walk_root_is_self_for_top_level(db):
    rid = str(uuid.uuid4())
    db.add(Chat(id=rid, user_id="u", title="root", parent_chat_id=None))
    await db.commit()
    assert await te._walk_chat_to_root(rid, db) == rid


@pytest.mark.asyncio
async def test_walk_root_through_ancestry(db):
    rid, mid, leaf = (str(uuid.uuid4()) for _ in range(3))
    db.add(Chat(id=rid, user_id="u", title="root", parent_chat_id=None))
    db.add(Chat(id=mid, user_id="u", title="mid", parent_chat_id=rid))
    db.add(Chat(id=leaf, user_id="u", title="leaf", parent_chat_id=mid))
    await db.commit()
    assert await te._walk_chat_to_root(leaf, db) == rid


# ── cumulative cap ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cumulative_cap_blocks_after_limit(db, monkeypatch):
    rid = str(uuid.uuid4())
    db.add(Chat(id=rid, user_id="u", title="root", parent_chat_id=None))
    await db.commit()
    _patch_redis(monkeypatch, _FakeRedis())
    _set_caps(monkeypatch, total=3, rate=0)  # rate off, cumulative=3

    # First 3 spawns allowed, 4th rejected.
    for _ in range(3):
        assert await te._enforce_root_spawn_caps(rid, db) is None
    msg = await te._enforce_root_spawn_caps(rid, db)
    assert msg is not None and "Sub-agent limit reached" in msg


# ── rate cap ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_cap_blocks_burst(db, monkeypatch):
    rid = str(uuid.uuid4())
    db.add(Chat(id=rid, user_id="u", title="root", parent_chat_id=None))
    await db.commit()
    _patch_redis(monkeypatch, _FakeRedis())
    _set_caps(monkeypatch, total=0, rate=2)  # cumulative off, rate=2/window

    assert await te._enforce_root_spawn_caps(rid, db) is None
    assert await te._enforce_root_spawn_caps(rid, db) is None
    msg = await te._enforce_root_spawn_caps(rid, db)
    assert msg is not None and "Spawn-rate limit reached" in msg


# ── disabled / fail-open ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_when_both_zero(db, monkeypatch):
    rid = str(uuid.uuid4())
    db.add(Chat(id=rid, user_id="u", title="root", parent_chat_id=None))
    await db.commit()
    _set_caps(monkeypatch, total=0, rate=0)
    # No redis patch needed — should short-circuit before touching it.
    for _ in range(50):
        assert await te._enforce_root_spawn_caps(rid, db) is None


@pytest.mark.asyncio
async def test_fails_open_when_redis_unavailable(db, monkeypatch):
    rid = str(uuid.uuid4())
    db.add(Chat(id=rid, user_id="u", title="root", parent_chat_id=None))
    await db.commit()
    _set_caps(monkeypatch, total=1, rate=1)

    def _boom():
        raise RuntimeError("redis down")
    monkeypatch.setattr("src.core.redis.get_redis", _boom)
    # Must not raise and must allow the spawn (backstop never wedges work).
    assert await te._enforce_root_spawn_caps(rid, db) is None


@pytest.mark.asyncio
async def test_fails_closed_when_configured(db, monkeypatch):
    rid = str(uuid.uuid4())
    db.add(Chat(id=rid, user_id="u", title="root", parent_chat_id=None))
    await db.commit()
    _set_caps(monkeypatch, total=1, rate=1)
    from src.core.config import get_settings
    monkeypatch.setattr(get_settings(), "spawn_caps_fail_closed", True, raising=False)

    def _boom():
        raise RuntimeError("redis down")
    monkeypatch.setattr("src.core.redis.get_redis", _boom)
    msg = await te._enforce_root_spawn_caps(rid, db)
    assert msg is not None and "fail-closed" in msg


# ── peek mode (count=False) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_peek_mode_does_not_increment(db, monkeypatch):
    rid = str(uuid.uuid4())
    db.add(Chat(id=rid, user_id="u", title="root", parent_chat_id=None))
    await db.commit()
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    _set_caps(monkeypatch, total=3, rate=0)

    # Repeated peeks never consume budget.
    for _ in range(10):
        assert await te._enforce_root_spawn_caps(rid, db, count=False) is None
    assert fake.store == {}

    # Authoritative dispatch-side counting consumes it; peek then rejects.
    for _ in range(3):
        assert await te._enforce_root_spawn_caps(rid, db, count=True) is None
    msg = await te._enforce_root_spawn_caps(rid, db, count=False)
    assert msg is not None and "Sub-agent limit reached" in msg
    # And the rejected peek did not bump the counter further.
    assert fake.store[f"spawn_total:{rid}"] == 3
