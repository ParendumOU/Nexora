"""Unit tests for the stop-button hard-cancel: ancestor-cancel propagation
(chat_cancel.is_ancestor_cancelled) — the gate that stops a runaway delegation
loop where sub-chats spawned AFTER the stop snapshot would otherwise keep running.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models  # noqa: F401
from src.models.chat import Chat
import src.services.chat_cancel as cc


@pytest_asyncio.fixture
async def db_factory(monkeypatch):
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    # is_ancestor_cancelled opens AsyncSessionLocal internally — point it at ours.
    monkeypatch.setattr("src.core.database.AsyncSessionLocal", factory)
    yield factory
    await eng.dispose()


class _FakeRedis:
    def __init__(self, flagged=None):
        self.flagged = set(flagged or [])
    async def get(self, key):
        return "1" if key in self.flagged else None


def _patch_redis(monkeypatch, flagged):
    monkeypatch.setattr("src.core.redis.get_redis", lambda: _FakeRedis(flagged))


async def _mk_chain(factory):
    """root → mid → leaf; return ids."""
    root, mid, leaf = (str(uuid.uuid4()) for _ in range(3))
    async with factory() as db:
        db.add(Chat(id=root, user_id="u", title="root", parent_chat_id=None))
        db.add(Chat(id=mid, user_id="u", title="mid", parent_chat_id=root))
        db.add(Chat(id=leaf, user_id="u", title="leaf", parent_chat_id=mid))
        await db.commit()
    return root, mid, leaf


@pytest.mark.asyncio
async def test_leaf_sees_root_cancel(db_factory, monkeypatch):
    root, mid, leaf = await _mk_chain(db_factory)
    _patch_redis(monkeypatch, flagged={cc._cancel_key(root)})
    # A leaf sub-chat created after the stop must see the root's flag.
    assert await cc.is_ancestor_cancelled(leaf) is True


@pytest.mark.asyncio
async def test_leaf_sees_mid_cancel(db_factory, monkeypatch):
    root, mid, leaf = await _mk_chain(db_factory)
    _patch_redis(monkeypatch, flagged={cc._cancel_key(mid)})
    assert await cc.is_ancestor_cancelled(leaf) is True


@pytest.mark.asyncio
async def test_no_cancel_anywhere(db_factory, monkeypatch):
    root, mid, leaf = await _mk_chain(db_factory)
    _patch_redis(monkeypatch, flagged=set())
    assert await cc.is_ancestor_cancelled(leaf) is False


@pytest.mark.asyncio
async def test_self_cancel(db_factory, monkeypatch):
    root, mid, leaf = await _mk_chain(db_factory)
    _patch_redis(monkeypatch, flagged={cc._cancel_key(leaf)})
    assert await cc.is_ancestor_cancelled(leaf) is True


@pytest.mark.asyncio
async def test_fails_open_on_redis_error(db_factory, monkeypatch):
    root, mid, leaf = await _mk_chain(db_factory)
    def _boom():
        raise RuntimeError("redis down")
    monkeypatch.setattr("src.core.redis.get_redis", _boom)
    # Must not raise and must not block (returns False).
    assert await cc.is_ancestor_cancelled(leaf) is False


# ── cancel_chat_tree: fast subtree cancel (recursive CTE + pipelined flags) ─────

class _FakePipe:
    def __init__(self, store):
        self.store = store
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    def setex(self, k, ttl, v):
        self.store.add(k)
    def delete(self, *ks):
        pass
    async def execute(self):
        return None


class _FakeRedisPipe:
    def __init__(self):
        self.flags = set()
    def pipeline(self, transaction=False):
        return _FakePipe(self.flags)
    async def setex(self, k, ttl, v):
        self.flags.add(k)
    async def get(self, k):
        return "1" if k in self.flags else None


@pytest.mark.asyncio
async def test_cancel_chat_tree_cancels_whole_subtree(db_factory, monkeypatch):
    from src.models.task import Task

    from src.models.goal import Goal

    root, mid, leaf = await _mk_chain(db_factory)
    async with db_factory() as db:
        db.add(Task(id="t-root", org_id="o", chat_id=root, title="a", status="in_progress"))
        db.add(Task(id="t-mid", org_id="o", chat_id=mid, title="b", status="queued"))
        db.add(Task(id="t-leaf", org_id="o", chat_id=leaf, title="c", status="pending"))
        db.add(Task(id="t-done", org_id="o", chat_id=leaf, title="d", status="completed"))
        # An active autopilot goal hosted in the root chat must be PAUSED by the cancel so
        # startup recovery can't revive the run on the next redeploy.
        db.add(Goal(id="g1", org_id="o", title="G", status="active", chat_id=root))
        await db.commit()

    fake = _FakeRedisPipe()
    monkeypatch.setattr("src.core.redis.get_redis", lambda: fake)
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("src.core.pubsub.broadcast", _noop)
    monkeypatch.setattr("src.core.stream_buffer.clear", _noop)
    monkeypatch.setattr("src.services.interrupt_store.signal_interrupt", _noop)

    res = await cc.cancel_chat_tree(root)

    # All three active tasks across the subtree are failed; the completed one untouched.
    assert res["cancelled_tasks"] == 3
    assert res["cancelled_in_chats"] == 3
    async with db_factory() as db:
        statuses = {t.id: t.status for t in (await db.execute(__import__("sqlalchemy").select(Task))).scalars().all()}
    assert statuses["t-root"] == "failed"
    assert statuses["t-mid"] == "failed"
    assert statuses["t-leaf"] == "failed"
    assert statuses["t-done"] == "completed"
    # A cancel flag was set for every chat in the subtree (so each loop's own-flag poll fires).
    assert cc._cancel_key(root) in fake.flags
    assert cc._cancel_key(leaf) in fake.flags
    # The active goal is now paused (won't be revived by startup recovery).
    from src.models.goal import Goal as _Goal
    async with db_factory() as db:
        g = await db.get(_Goal, "g1")
    assert g.status == "paused"
