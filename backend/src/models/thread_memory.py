import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


MEMORY_TYPES = {"fact", "decision", "context", "instruction"}


class ThreadMemory(Base):
    """Shared memory for an entire conversation thread (root chat + all sub-chats).

    All agents operating within the same thread (parent + subchats) share and
    read from the same pool of ThreadMemory rows, keyed on root_chat_id.
    """
    __tablename__ = "thread_memories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Top-level parent chat that anchors the thread
    root_chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    # Which sub-chat or parent chat wrote this entry
    chat_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    # Which agent wrote this entry
    agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Optional short key for namespacing (e.g. "auth_flow", "stack", "todos")
    key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    type: Mapped[str] = mapped_column(String(20), default="fact")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional structured data blob (list, dict, etc.)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1–5

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
