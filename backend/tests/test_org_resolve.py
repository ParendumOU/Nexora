"""Shared org-resolution helper (org-resolution sweep).

resolve_chat_org must resolve the org for any tool call: from the calling agent,
else by walking the chat's parent chain (each chat's agent / project), else the
human-owned root chat user's active org. This is what lets a delegated sub-agent
(sub-chat owned by the system user) or a builtin/row-less orchestrator resolve the
correct org instead of None / the wrong org.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.services.org_resolve import resolve_chat_org
from src.models.user import User
from src.models.org import Organization, OrgMember
from src.models.chat import Chat
from src.models.agent import Agent


@pytest.mark.asyncio
async def test_resolves_via_calling_agent(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    org, agent = str(uuid.uuid4()), str(uuid.uuid4())
    human = str(uuid.uuid4())
    async with factory() as s:
        s.add(User(id=human, email=f"u-{human[:8]}@t.t", hashed_password="x", full_name="U", active_org_id=org))
        await s.flush()
        s.add(Organization(id=org, name="O", slug=f"o-{org[:8]}", owner_id=human))
        await s.flush()
        s.add(Agent(id=agent, org_id=org, name="A", agent_type="assistant"))
        await s.commit()
    async with factory() as s:
        assert await resolve_chat_org(s, None, agent) == org
        for t in (Agent, Organization, User):
            await s.execute(t.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_resolves_subchat_via_root_user_when_no_agent(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    human, sysu, org = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    root, sub = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(User(id=human, email=f"h-{human[:8]}@t.t", hashed_password="x", full_name="H", active_org_id=org))
        s.add(User(id=sysu, email=f"s-{sysu[:8]}@t.t", hashed_password="x", full_name="System"))
        await s.flush()
        s.add(Organization(id=org, name="O", slug=f"o-{org[:8]}", owner_id=human))
        await s.flush()
        s.add(OrgMember(org_id=org, user_id=human))
        s.add(Chat(id=root, user_id=human, title="root"))
        # System-user sub-chat, no agent → must walk to the human root's active org.
        s.add(Chat(id=sub, user_id=sysu, parent_chat_id=root, title="sub"))
        await s.commit()
    async with factory() as s:
        assert await resolve_chat_org(s, sub, "builtin-no-row") == org
        for t in (Chat, OrgMember, Organization, User):
            await s.execute(t.__table__.delete())
        await s.commit()


@pytest.mark.asyncio
async def test_none_when_orphaned(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        assert await resolve_chat_org(s, "no-such-chat", "no-such-agent") is None
