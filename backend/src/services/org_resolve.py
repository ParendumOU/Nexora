"""Shared org resolution for tool executors (GitLab #-org-resolution sweep).

A tool runs with a chat_id + (optional) agent_id. Resolving the org from the agent
alone breaks for (a) builtin/seed agents that have no org-scoped Agent row, and
(b) delegated sub-agents whose sub-chat is owned by the SYSTEM user — the old
user-membership fallback then picked the system user's org and DB-scoped queries
hit the wrong/empty org.

`resolve_chat_org` resolves consistently: the calling agent's org → walk the chat's
parent chain trying each chat's org-scoped agent, then its project → the human-owned
root chat's user active org / first membership. Returns None only when nothing in the
chain has an org (a truly orphaned chat).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_chat_org(db: AsyncSession, chat_id: str | None, agent_id: str | None = None) -> str | None:
    from src.models.agent import Agent
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.user import User
    from src.models.org import OrgMember

    # 1. The calling agent is org-scoped → most direct signal.
    if agent_id:
        ag = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if ag and ag.org_id:
            return ag.org_id

    # 2. Walk the chat's parent chain: each chat's agent (org-scoped), then project.
    visited: set[str] = set()
    cur_id = chat_id
    root_user_id: str | None = None
    while cur_id and cur_id not in visited:
        visited.add(cur_id)
        chat = (await db.execute(select(Chat).where(Chat.id == cur_id))).scalar_one_or_none()
        if not chat:
            break
        if chat.agent_id:
            ag2 = (await db.execute(select(Agent).where(Agent.id == chat.agent_id))).scalar_one_or_none()
            if ag2 and ag2.org_id:
                return ag2.org_id
        if chat.project_id:
            po = (await db.execute(select(Project.org_id).where(Project.id == chat.project_id))).scalar_one_or_none()
            if po:
                return po
        root_user_id = chat.user_id or root_user_id
        if not chat.parent_chat_id:
            break
        cur_id = chat.parent_chat_id

    # 3. Human-owned root: their active org, else first membership.
    if root_user_id:
        u = (await db.execute(select(User).where(User.id == root_user_id))).scalar_one_or_none()
        if u and u.active_org_id:
            return u.active_org_id
        m = (await db.execute(select(OrgMember).where(OrgMember.user_id == root_user_id).limit(1))).scalar_one_or_none()
        if m:
            return m.org_id
    return None
