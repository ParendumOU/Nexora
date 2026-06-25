"""Local-exec bridge: same-worker resolve + cross-worker result routing (#224)."""
import asyncio

import pytest

from src.services.agent_tools import local_exec as le


@pytest.fixture(autouse=True)
def _clean_bridges():
    le._bridges.clear()
    yield
    le._bridges.clear()


@pytest.mark.asyncio
async def test_same_worker_resolve_fast_path(monkeypatch):
    # No pubsub needed: register's subscribe failure is tolerated, resolve hits local.
    sent = []
    bridge = le.LocalExecBridge("chatA", lambda ev: sent.append(ev) or _noop())
    le._bridges["chatA"] = bridge

    async def _call():
        return await bridge.run("file_read", {"path": "/x"})

    task = asyncio.create_task(_call())
    await asyncio.sleep(0.05)
    rid = sent[0]["request_id"]
    ok = await le.resolve("chatA", rid, {"data": {"content": "hi"}})
    assert ok is True
    result = await task
    assert result == {"data": {"content": "hi"}}


async def _noop():
    return None


@pytest.mark.asyncio
async def test_cross_worker_publishes_when_no_local_bridge(monkeypatch):
    # Simulate the result arriving on a worker that does NOT hold the bridge:
    # resolve must republish on the private channel.
    published = []

    async def _fake_broadcast(key, event):
        published.append((key, event))

    monkeypatch.setattr("src.core.pubsub.broadcast", _fake_broadcast)

    ok = await le.resolve("chatGhost", "req-1", {"data": {"ok": True}})
    assert ok is True
    assert published == [("localexec_result:chatGhost", {"request_id": "req-1", "result": {"data": {"ok": True}}})]


@pytest.mark.asyncio
async def test_run_aborts_on_cancel(monkeypatch):
    # A user cancel mid-wait must abort the local-exec wait promptly (#223) instead
    # of blocking the full timeout.
    monkeypatch.setattr(le, "LOCAL_EXEC_TIMEOUT", 30.0)
    cancelled = {"v": False}

    async def _is_cancelled(_chat_id):
        return cancelled["v"]

    monkeypatch.setattr("src.services.chat_cancel.is_cancelled", _is_cancelled)
    sent = []
    bridge = le.LocalExecBridge("chatC", lambda ev: sent.append(ev) or _noop())

    async def _call():
        return await bridge.run("shell_run", {"command": "sleep 999"})

    task = asyncio.create_task(_call())
    await asyncio.sleep(0.05)
    cancelled["v"] = True  # user cancels; the client never replies
    result = await asyncio.wait_for(task, timeout=3)
    assert result.get("error") == "local exec cancelled by user"


@pytest.mark.asyncio
async def test_result_listener_resolves_future(monkeypatch):
    # The bridge's cross-worker listener resolves a pending Future from a queued msg.
    sent = []
    bridge = le.LocalExecBridge("chatB", lambda ev: sent.append(ev) or _noop())
    le._bridges["chatB"] = bridge
    q: asyncio.Queue = asyncio.Queue()
    bridge._result_q = q
    bridge._result_task = asyncio.create_task(le._result_listener(bridge, q))

    task = asyncio.create_task(bridge.run("shell_run", {"command": "ls"}))
    await asyncio.sleep(0.05)
    rid = sent[0]["request_id"]
    # A result published by another worker arrives via the queue.
    await q.put({"request_id": rid, "result": {"data": {"stdout": "ok"}}})
    result = await asyncio.wait_for(task, timeout=2)
    assert result == {"data": {"stdout": "ok"}}
    bridge._result_task.cancel()
