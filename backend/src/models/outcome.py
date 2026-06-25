"""Outcome tracking + decision log (GitLab #236, Autonomy epic #238).

Closes the act -> observe -> learn loop. An `Outcome` row records either:
  - an OUTCOME: what an action/goal/task achieved (success/failure/partial) with an
    optional metric/KPI, or
  - a DECISION: what was decided and why (rationale), so agents can review past
    decisions instead of repeating them.

Recorded automatically when a goal/milestone completes and when a goal-linked task
fails, plus on demand via the outcome_record agent tool. Queryable for learning.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    # outcome | decision
    kind: Mapped[str] = mapped_column(String(20), default="outcome", server_default="outcome", nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)  # what this is about
    # success | failure | partial | info  (for outcomes; "info" for decisions)
    status: Mapped[str] = mapped_column(String(20), default="info", server_default="info", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # what happened / rationale
    metric_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # optional links to the thing this outcome is about
    ref_type: Mapped[str | None] = mapped_column(String(20), nullable=True)   # goal | task | milestone | action
    ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="agent", server_default="agent")  # agent | system

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
