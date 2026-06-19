import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), nullable=True)
    parent_chat_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("chats.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), default="New Chat")
    provider_chain_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("provider_chains.id"), nullable=True)
    direct_provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("providers.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sync_response: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sync_timeout: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="chats")  # noqa: F821
    project: Mapped["Project | None"] = relationship("Project", back_populates="chats")  # noqa: F821
    parent_chat: Mapped["Chat | None"] = relationship("Chat", remote_side=[id], back_populates="child_chats")  # noqa: F821
    child_chats: Mapped[list["Chat"]] = relationship("Chat", back_populates="parent_chat")  # noqa: F821
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="chat",
        order_by="Message.created_at", lazy="select",
        cascade="all, delete-orphan",
    )
    participants: Mapped[list["ChatParticipant"]] = relationship(
        "ChatParticipant", back_populates="chat", lazy="select",
        cascade="all, delete-orphan",
    )
    structured_notes: Mapped[list["ChatNote"]] = relationship(
        "ChatNote", back_populates="chat", lazy="select",
        cascade="all, delete-orphan",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False)   # user, assistant, system, tool_result
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    provider_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chat: Mapped["Chat"] = relationship("Chat", back_populates="messages")
    sender: Mapped["User | None"] = relationship("User", foreign_keys=[user_id])  # noqa: F821


class ChatParticipant(Base):
    __tablename__ = "chat_participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="participant")  # owner, participant
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chat: Mapped["Chat"] = relationship("Chat", back_populates="participants")
    user: Mapped["User"] = relationship("User")  # noqa: F821


class ChatNote(Base):
    __tablename__ = "chat_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_chat_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chat: Mapped["Chat"] = relationship("Chat", back_populates="structured_notes")
