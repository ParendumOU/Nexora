import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Nullable: a message can originate from the conversation's default assistant,
    # which has no org-scoped Agent row (sending one with from_agent_id="" or a
    # non-existent id FK-crashed and looped). None = "from the conversation".
    from_agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id"), nullable=True, index=True)
    to_agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agent_messages.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | delivered | replied | timeout
    reply_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(10), default="sync")  # sync | async
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
