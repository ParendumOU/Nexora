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
