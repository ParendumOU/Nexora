"""knowledge_search org resolution walks to the right org for a delegated sub-agent.

Server-testing bug: a delegated KB Researcher ran in a sub-chat owned by the system
user, so the old resolver picked the system user's first org membership and the
search hit an empty KB ("no encontré nada"). It now resolves via the chat's
org-scoped agent (and walks the parent chain), so the sub-agent searches the same
org as the human who asked.
"""
import importlib.util
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.models.user import User
from src.models.org import Organization, OrgMember
from src.models.chat import Chat
from src.models.agent import Agent


def _load():
    spec = importlib.util.spec_from_file_location(
        "ks_exec", "src/seeds/tools/builtin/knowledge_search/executor.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.asyncio
async def test_subchat_org_resolves_via_agent(engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    mod = _load()
    monkeypatch.setattr(mod, "AsyncSessionLocal", factory, raising=False)

    human, sysu = str(uuid.uuid4()), str(uuid.uuid4())
    org = str(uuid.uuid4())
    agent = str(uuid.uuid4())
    parent_chat, sub_chat = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(User(id=human, email=f"h-{human[:8]}@t.t", hashed_password="x", full_name="H", active_org_id=org))
        s.add(User(id=sysu, email=f"sys-{sysu[:8]}@t.t", hashed_password="x", full_name="System"))
        await s.flush()
        s.add(Organization(id=org, name="O", slug=f"o-{org[:8]}", owner_id=human))
        await s.flush()
        s.add(OrgMember(org_id=org, user_id=human))
        # KB Researcher copy scoped to the human's org.
        s.add(Agent(id=agent, org_id=org, name="KB Researcher", agent_type="assistant"))
        # Human's root chat, then a system-user-owned sub-chat driven by the org agent.
        s.add(Chat(id=parent_chat, user_id=human, title="root"))
        s.add(Chat(id=sub_chat, user_id=sysu, agent_id=agent, parent_chat_id=parent_chat, title="sub"))
        await s.commit()

    # The sub-chat is owned by the system user, but its agent is org-scoped → correct org.
    assert await mod._get_org_id(sub_chat) == org

    # Also resolves the human root's active org when no agent/project is on the chain.
    plain_root = str(uuid.uuid4())
    plain_sub = str(uuid.uuid4())
    async with factory() as s:
        s.add(Chat(id=plain_root, user_id=human, title="root2"))
        s.add(Chat(id=plain_sub, user_id=sysu, parent_chat_id=plain_root, title="sub2"))
        await s.commit()
    assert await mod._get_org_id(plain_sub) == org

    async with factory() as s:
        for t in (Chat, Agent, OrgMember, Organization, User):
            await s.execute(t.__table__.delete())
        await s.commit()
