"""Human-in-the-loop tool approval (GitLab #235, Autonomy epic #238).

When `require_approval_tier` gates a tool, the dispatcher does NOT run it; it
records a pending `ToolApproval` (the tool name + args + where it came from) and
returns a blocking result so the agent stops. A human approves or denies via the
approvals API; on approve the tool is executed and the chat resumes.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class ToolApproval(Base):
    __tablename__ = "tool_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True, index=True)
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_args: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_tier: Mapped[str] = mapped_column(String(20), default="write")
    # pending | approved | denied
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False, index=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # tool result after execution

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
