"""Durable goal/objective hierarchy (GitLab #232, Autonomy Layer epic #238).

The missing layer ABOVE ephemeral per-chat tasks/plans: a `Goal` an org pursues
over time, decomposed into `Milestone`s, which link to the existing `Task`s that
implement them. Goals survive restarts and are the unit of self-management.

Status roll-up (milestones done → goal progress) and decomposition logic live in
`services/goals.py`; this module is just the schema.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    # Self-reference: a goal can be a sub-goal of a larger objective.
    parent_goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Agent accountable for advancing this goal (nullable = unassigned / org-level).
    owner_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-text / structured acceptance criteria — what "achieved" means. Verified
    # by the acceptance-criteria loop (#233).
    success_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active | blocked | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # 0-100 roll-up from milestone completion.
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    milestones: Mapped[list["Milestone"]] = relationship(
        "Milestone",
        back_populates="goal",
        order_by="Milestone.position",
        cascade="all, delete-orphan",
        lazy="select",
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    goal_id: Mapped[str] = mapped_column(String(36), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending | in_progress | done | failed | skipped
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    goal: Mapped["Goal"] = relationship("Goal", back_populates="milestones")
