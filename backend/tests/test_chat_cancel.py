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
