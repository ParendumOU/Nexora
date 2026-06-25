"""Persistent agent-org helpers (GitLab #237)."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.agent_role import AgentRole

logger = logging.getLogger(__name__)


async def assign_role(
    *, org_id: str, agent_id: str, title: str, area: str | None = None,
    escalates_to_agent_id: str | None = None, priority: int = 0,
) -> str | None:
    """Create/update an agent's role. One active role row per (org, agent, title);
    re-assigning the same title updates the area/escalation. Returns the role id."""
    if not org_id or not agent_id or not (title or "").strip():
        return None
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(AgentRole).where(
                AgentRole.org_id == org_id, AgentRole.agent_id == agent_id,
                AgentRole.title == title.strip(), AgentRole.is_active == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if existing:
            existing.area = area
            existing.escalates_to_agent_id = escalates_to_agent_id
            existing.priority = priority
            await db.commit()
            return existing.id
        row = AgentRole(
            id=str(uuid.uuid4()), org_id=org_id, agent_id=agent_id, title=title.strip(),
            area=area, escalates_to_agent_id=escalates_to_agent_id, priority=priority,
        )
        db.add(row)
        await db.commit()
        return row.id


async def list_roles(org_id: str) -> list[dict]:
    """Active org roles with agent names, highest priority first."""
    if not org_id:
        return []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AgentRole).where(AgentRole.org_id == org_id, AgentRole.is_active == True)  # noqa: E712
            .order_by(AgentRole.priority.desc(), AgentRole.created_at)
        )).scalars().all()
        names = {a.id: a.name for a in (await db.execute(select(Agent).where(Agent.org_id == org_id))).scalars().all()}
    return [{
        "id": r.id, "agent_id": r.agent_id, "agent_name": names.get(r.agent_id),
        "title": r.title, "area": r.area, "priority": r.priority,
        "escalates_to_agent_id": r.escalates_to_agent_id,
        "escalates_to_agent_name": names.get(r.escalates_to_agent_id) if r.escalates_to_agent_id else None,
    } for r in rows]
