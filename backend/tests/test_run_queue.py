"""Durable run queue — routing, decode, governor, disabled no-op (GitLab #219)."""
import json

import pytest

import src.services.run_queue as rq


# ── enqueue gating ───────────────────────────────────────────────────────────


async def test_enqueue_disabled_is_noop(monkeypatch):
    # default: run_queue_enabled is False → enqueue returns None without touching Redis
    assert rq.is_enabled() is False
    assert await rq.enqueue_run("subagent", task_id="t1", org_id="o1") is None


async def test_enqueue_bad_kind_raises():
    with pytest.raises(ValueError):
        await rq.enqueue_run("not_a_kind")


# ── message decode ───────────────────────────────────────────────────────────


def test_decode_str_fields():
    kind, data = rq._decode({"kind": "subagent", "data": json.dumps({"task_id": "t1"})})
    assert kind == "subagent" and data == {"task_id": "t1"}


def test_decode_bytes_fields():
    raw = {b"kind": b"resume_tools", b"data": json.dumps({"chat_id": "c1"}).encode()}
    kind, data = rq._decode(raw)
    assert kind == "resume_tools" and data == {"chat_id": "c1"}


def test_decode_missing_kind_returns_none():
    assert rq._decode({"data": "{}"}) is None


# ── routing ──────────────────────────────────────────────────────────────────


async def test_dispatch_routes_subagent(monkeypatch):
    seen = {}

    async def _fake_exec(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(rq, "acquire_slot", lambda *a, **k: _true())
    monkeypatch.setattr(rq, "release_slot", lambda *a, **k: _noop())
    import src.services.sub_agent.executor as ex
    monkeypatch.setattr(ex, "_execute_sub_agent_task", _fake_exec)

    await rq.dispatch_run("subagent", {
        "task_id": "t1", "parent_chat_id": "c1", "org_id": "o1",
        "parent_chat_project_id": "p1", "parent_chat_provider_chain_id": None,
        "user_id": "u1", "parent_direct_provider_id": None, "agent_id": "a1",
    })
    assert seen["task_id"] == "t1" and seen["parent_chat_id"] == "c1"
    assert seen["org_id"] == "o1" and seen["user_id"] == "u1"


async def test_dispatch_routes_resume_orchestrator(monkeypatch):
    seen = {}

    async def _fake(parent_chat_id, org_id, user_id, force_continue=False):
        seen.update(dict(parent_chat_id=parent_chat_id, org_id=org_id, user_id=user_id, fc=force_continue))

    import src.services.orchestrator as orch
    monkeypatch.setattr(orch, "_resume_orchestrator", _fake)
    await rq.dispatch_run("resume_orchestrator", {"parent_chat_id": "c1", "org_id": "o1", "user_id": "u1", "force_continue": True})
    assert seen == {"parent_chat_id": "c1", "org_id": "o1", "user_id": "u1", "fc": True}


async def test_dispatch_unknown_kind_is_safe():
    # no handler, must not raise
    await rq.dispatch_run("bogus", {})


# ── governor ─────────────────────────────────────────────────────────────────


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def incr(self, k):
        self.store[k] = self.store.get(k, 0) + 1
        return self.store[k]

    async def decr(self, k):
        self.store[k] = self.store.get(k, 0) - 1
        return self.store[k]

    async def expire(self, k, t):
        return True

    async def set(self, k, v):
        self.store[k] = v


async def test_governor_org_cap(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(rq, "get_redis", lambda: fake)
    from src.core.config import get_settings
    cap = get_settings().max_concurrent_agents_per_org
    # acquire up to the cap (no agent_id → only org counter)
    for _ in range(cap):
        assert await rq.acquire_slot("o1", None) is True
    # next one over the cap is refused, and the over-increment is rolled back
    assert await rq.acquire_slot("o1", None) is False
    assert fake.store["cc:org:o1"] == cap
    await rq.release_slot("o1", None)
    assert fake.store["cc:org:o1"] == cap - 1


async def test_governor_no_org_always_true(monkeypatch):
    monkeypatch.setattr(rq, "get_redis", lambda: _FakeRedis())
    assert await rq.acquire_slot(None, None) is True


# helpers
async def _true():
    return True


async def _noop():
    return None
