"""AgentProposal — structured suggestions agents emit for human (or auto) review."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


PROPOSAL_STATUSES = {"pending", "approved", "rejected", "auto_approved"}

PROPOSAL_TYPES = {
    "create_issue",
    "create_task",
    "spawn_agent",
    "trigger_pipeline",
    "modify_schedule",
    "custom",
}


class AgentProposal(Base):
    __tablename__ = "agent_proposals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    chat_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chats.id"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    proposal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )

    # Result of execution (set after auto_approved or approved)
    execution_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    agent = relationship("Agent", foreign_keys=[agent_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])
