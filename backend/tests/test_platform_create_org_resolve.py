"""platform_create_* org resolution falls back to the chat user's active org.

Server-testing bug: creating an agent failed with 'Could not resolve org_id' when
the chat ran on a builtin agent with no org-scoped Agent row. The resolver now
falls back through project → chat user's active org.
"""
import importlib.util
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.models.user import User
from src.models.org import Organization, OrgMember
from src.models.chat import Chat


def _load(tool: str):
    p = f"src/seeds/tools/builtin/{tool}/executor.py"
    spec = importlib.util.spec_from_file_location(f"ex_{tool}", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [
    "platform_create_agent", "platform_create_skill",
    "platform_create_tool", "platform_create_persona",
])
async def test_resolve_org_falls_back_to_chat_user_active_org(tool, engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    mod = _load(tool)
    # Point the executor's own session factory at the in-memory test engine.
    monkeypatch.setattr(mod, "AsyncSessionLocal", factory, raising=False)

    uid, oid, cid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(User(id=uid, email=f"org-{uid[:8]}@t.t", hashed_password="x", full_name="U", active_org_id=oid))
        await s.flush()
        s.add(Organization(id=oid, name="O", slug=f"o-{oid[:8]}", owner_id=uid))
        await s.flush()
        s.add(OrgMember(org_id=oid, user_id=uid))
        # agent_id has NO Agent row → must fall through to the user's active org.
        s.add(Chat(id=cid, user_id=uid, agent_id="builtin-seed-key-no-row", title="c"))
        await s.commit()

    org = await mod._resolve_org("builtin-seed-key-no-row", cid)
    assert org == oid

    # cleanup (shared in-memory DB across the session-scoped engine)
    async with factory() as s:
        for t in (Chat, OrgMember, Organization, User):
            await s.execute(t.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_resolve_org_none_when_no_context(engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    mod = _load("platform_create_agent")
    monkeypatch.setattr(mod, "AsyncSessionLocal", factory, raising=False)
    assert await mod._resolve_org(None, "nonexistent-chat") is None
