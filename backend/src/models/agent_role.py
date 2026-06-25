"""Persistent agent organisation (GitLab #237, Autonomy epic #238).

A standing org chart: which agent owns which area, with a role title and optional
escalation target. Outlives ephemeral spawn-trees so ownership/accountability and
the backlog planner have a durable structure to reason over.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class AgentRole(Base):
    __tablename__ = "agent_roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)        # e.g. "Backend Lead"
    area: Mapped[str | None] = mapped_column(String(200), nullable=True)   # area of ownership (free text / tag)
    # Agent to escalate to when this one is blocked / over capacity.
    escalates_to_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
