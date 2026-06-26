"""Agent-messaging + agent-listing org resolution (server-testing bug).

send_message_to_agent failed "Cannot message agent from a different org" because the
sender's org was resolved only from the (possibly row-less builtin) agent, leaving it
None so EVERY recipient looked cross-org. Both tools now resolve org via
agent → parent-chat agent → project → the chat user's active org.
"""
import importlib.util
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.models.user import User
from src.models.org import Organization, OrgMember
from src.models.chat import Chat
from src.models.agent import Agent


def _load(tool: str):
    spec = importlib.util.spec_from_file_location(f"ex_{tool}", f"src/seeds/tools/builtin/{tool}/executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


async def _seed(factory, *, with_recipient=True):
    human, org = str(uuid.uuid4()), str(uuid.uuid4())
    recipient = str(uuid.uuid4())
    chat = str(uuid.uuid4())
    async with factory() as s:
        s.add(User(id=human, email=f"h-{human[:8]}@t.t", hashed_password="x", full_name="H", active_org_id=org))
        await s.flush()
        s.add(Organization(id=org, name="O", slug=f"o-{org[:8]}", owner_id=human))
        await s.flush()
        s.add(OrgMember(org_id=org, user_id=human))
        if with_recipient:
            s.add(Agent(id=recipient, org_id=org, name="KB Researcher", agent_type="assistant", is_active=True))
        # Chat driven by a builtin/seed agent id that has NO Agent row.
        s.add(Chat(id=chat, user_id=human, agent_id="builtin-orchestrator-no-row", title="c"))
        await s.commit()
    return human, org, recipient, chat


@pytest.mark.asyncio
async def test_send_message_resolves_org_from_user_not_blocked(engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    mod = _load("send_message_to_agent")
    monkeypatch.setattr(mod, "AsyncSessionLocal", factory, raising=False)
    # Async mode proceeds past the cross-org guard into the Redis escalation-chain
    # check + a fire-and-forget dispatch; stub both so the test stays hermetic (no
    # live Redis / no real sub-agent run).
    _fake_redis = AsyncMock()
    _fake_redis.smembers = AsyncMock(return_value=set())
    monkeypatch.setattr("src.core.redis.get_redis", lambda: _fake_redis, raising=False)
    monkeypatch.setattr("src.services.sub_agent._run_delegated_tasks",
                        AsyncMock(return_value=None), raising=False)
    _, org, recipient, chat = await _seed(factory)

    # Sender agent id has no row → org must resolve via the chat user's active org, so
    # the same-org recipient is NOT rejected as cross-org. Use async mode to avoid the
    # blocking reply-poll; we only need to get PAST the cross-org guard.
    res = await mod.execute(
        {"to_agent_id": recipient, "subject": "hi", "body": "find Zephyr-9", "mode": "async"},
        chat, "builtin-orchestrator-no-row", "Orchestrator",
    )
    assert not (isinstance(res, dict) and res.get("error") == "Cannot message agent from a different org"), res

    async with factory() as s:
        for t in (Chat, Agent, OrgMember, Organization, User):
            await s.execute(t.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_send_message_still_blocks_true_cross_org(engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    mod = _load("send_message_to_agent")
    monkeypatch.setattr(mod, "AsyncSessionLocal", factory, raising=False)
    _, org, _, chat = await _seed(factory, with_recipient=False)
    # A recipient genuinely in another org must still be rejected.
    other = str(uuid.uuid4())
    async with factory() as s:
        s.add(Agent(id=other, org_id="some-other-org", name="Foreign", agent_type="assistant", is_active=True))
        await s.commit()
    res = await mod.execute(
        {"to_agent_id": other, "subject": "x", "body": "y", "mode": "async"},
        chat, "builtin-orchestrator-no-row", "Orchestrator",
    )
    assert res.get("error") == "Cannot message agent from a different org"

    async with factory() as s:
        for t in (Chat, Agent, OrgMember, Organization, User):
            await s.execute(t.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_reply_path_needs_no_to_agent_id(engine, monkeypatch):
    # A reply targets a message (reply_to_id), not an agent — it must succeed without
    # to_agent_id and without recipient validation (the original sender may be the
    # row-less default assistant).
    from src.models.agent_message import AgentMessage
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    mod = _load("send_message_to_agent")
    monkeypatch.setattr(mod, "AsyncSessionLocal", factory, raising=False)

    _, org, recipient, chat = await _seed(factory)
    msg_id = str(uuid.uuid4())
    async with factory() as s:
        # Original message with NO from_agent_id (sent by the conversation's assistant).
        s.add(AgentMessage(id=msg_id, from_agent_id=None, to_agent_id=recipient, chat_id=chat,
                           subject="q", body="find it", mode="sync", status="delivered"))
        await s.commit()

    res = await mod.execute({"reply_to_id": msg_id, "body": "XK-4471 / Marta Ruiz"},
                            chat, recipient, "KB Researcher")
    assert res.get("data", {}).get("status") == "reply_sent", res
    async with factory() as s:
        from sqlalchemy import select as _sel
        m = (await s.execute(_sel(AgentMessage).where(AgentMessage.id == msg_id))).scalar_one()
        assert m.status == "replied" and m.reply_body == "XK-4471 / Marta Ruiz"
    async with factory() as s:
        for t in (AgentMessage, Chat, Agent, OrgMember, Organization, User):
            await s.execute(t.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_list_available_agents_resolves_org_from_user(engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    mod = _load("list_available_agents")
    monkeypatch.setattr(mod, "AsyncSessionLocal", factory, raising=False)
    _, org, recipient, chat = await _seed(factory)

    res = await mod.execute({}, chat, "builtin-orchestrator-no-row", "Orchestrator")
    assert "error" not in res, res
    names = [a["name"] for a in res["data"]["agents"]]
    assert "KB Researcher" in names

    async with factory() as s:
        for t in (Chat, Agent, OrgMember, Organization, User):
            await s.execute(t.__table__.delete())
        await s.commit()
