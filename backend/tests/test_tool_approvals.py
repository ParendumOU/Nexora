"""Human-in-the-loop tool approval (GitLab #235)."""
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.services.agent_tools.risk import tool_requires_approval


def _s(tier):
    return SimpleNamespace(require_approval_tier=tier, deny_exec_tools=False, deny_external_tools=False)


def test_requires_approval_threshold():
    assert tool_requires_approval("shell_run", _s("")) is False
    assert tool_requires_approval("shell_run", _s("off")) is False
    assert tool_requires_approval("shell_run", _s("exec")) is True
    assert tool_requires_approval("slack", _s("exec")) is False
    assert tool_requires_approval("slack", _s("external")) is True
    assert tool_requires_approval("shell_run", _s("external")) is True
    assert tool_requires_approval("file_read", _s("external")) is False
    assert tool_requires_approval("file_read", _s("write")) is False
    assert tool_requires_approval("frobnicate", _s("write")) is True  # unknown → write


# ── API (paths that use the get_db override only) ──────────────────────────────
@pytest.mark.asyncio
async def test_approvals_requires_auth(client):
    resp = await client.get("/api/approvals")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_empty(client, auth_headers):
    resp = await client.get("/api/approvals", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_approve_not_found(client, auth_headers):
    resp = await client.post("/api/approvals/00000000-0000-0000-0000-000000000000/approve", headers=auth_headers)
    assert resp.status_code == 404


# ── service flow (AsyncSessionLocal pointed at the test engine) ────────────────
@pytest_asyncio.fixture
async def svc_db(engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # tool_approvals imports AsyncSessionLocal at module top → patch the module ref
    # (and the core one) so the service uses the in-memory test engine.
    monkeypatch.setattr("src.core.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("src.services.tool_approvals.AsyncSessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_record_pending_then_deny(svc_db, monkeypatch):
    import uuid
    from src.services import tool_approvals as svc
    from src.models.tool_approval import ToolApproval
    from sqlalchemy import select

    chat_id = str(uuid.uuid4())
    aid = await svc.record_pending_approval(
        chat_id=chat_id, message_id=None, agent_id=None, agent_name="A",
        tool_name="shell_run", tool_args={"command": "ls"}, tier="exec",
    )
    assert aid

    # idempotent: same pending call again → None (no duplicate)
    dup = await svc.record_pending_approval(
        chat_id=chat_id, message_id=None, agent_id=None, agent_name="A",
        tool_name="shell_run", tool_args={"command": "ls"}, tier="exec",
    )
    assert dup is None

    res = await svc.deny(aid, decided_by="u1")
    assert res["status"] == "denied"
    res2 = await svc.deny(aid, decided_by="u1")
    assert "error" in res2  # already decided

    async with svc_db() as db:
        a = (await db.execute(select(ToolApproval).where(ToolApproval.id == aid))).scalar_one()
        assert a.status == "denied" and a.decided_by == "u1"


# ── approve-always (similar, by command content) (#235) ────────────────────────

def test_similar_sig_is_content_based_and_tool_scoped():
    from src.services.tool_approvals import _similar_sig
    # whitespace differences in the command collapse to the same signature
    assert _similar_sig("shell_run", {"command": "ls -la"}) == _similar_sig("shell_run", {"command": "ls   -la "})
    # different command → different signature
    assert _similar_sig("shell_run", {"command": "ls"}) != _similar_sig("shell_run", {"command": "rm -rf /"})
    # same content, different tool → different signature (tool-scoped)
    assert _similar_sig("shell_run", {"command": "x"}) != _similar_sig("code_node", {"command": "x"})
    # cmd/code aliases are read; falls back to full args when neither present
    assert _similar_sig("code_python", {"code": "print(1)"}).startswith("code_python:")
    assert _similar_sig("slack", {"channel": "ops", "text": "hi"}).startswith("slack:")


class _FakeRedis:
    def __init__(self):
        self.sets = {}
    async def sadd(self, key, *vals):
        self.sets.setdefault(key, set()).update(vals)
    async def sismember(self, key, val):
        return val in self.sets.get(key, set())
    async def expire(self, key, ttl):
        return True


@pytest.mark.asyncio
async def test_approve_similar_skips_future_prompts(monkeypatch):
    from src.services import tool_approvals as svc
    fake = _FakeRedis()
    monkeypatch.setattr("src.core.redis.get_redis", lambda: fake)
    # keep it hermetic: don't touch the DB for the root-chat walk
    async def _root(cid): return cid
    monkeypatch.setattr(svc, "_root_chat_id", _root)

    chat = "chat-1"
    # not approved yet
    assert await svc.is_similar_approved(chat, "shell_run", {"command": "pytest -q"}) is False
    # user clicks "always allow similar"
    await svc.mark_approve_similar(chat, "shell_run", {"command": "pytest -q"})
    # the same command (even with different spacing) is now pre-approved
    assert await svc.is_similar_approved(chat, "shell_run", {"command": "pytest  -q "}) is True
    # a DIFFERENT command still needs approval
    assert await svc.is_similar_approved(chat, "shell_run", {"command": "rm -rf build"}) is False
    # and a different tool with the same text is not covered
    assert await svc.is_similar_approved(chat, "code_node", {"command": "pytest -q"}) is False


@pytest.mark.asyncio
async def test_is_similar_approved_fails_open_without_redis(monkeypatch):
    from src.services import tool_approvals as svc
    def _boom():
        raise RuntimeError("no redis")
    monkeypatch.setattr("src.core.redis.get_redis", _boom)
    # any Redis error → treat as not-approved (still prompt) rather than crash
    assert await svc.is_similar_approved("c", "shell_run", {"command": "ls"}) is False
