import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text, ForeignKey, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class MemoryNote(Base):
    """A structured markdown memory note (Obsidian-style vault entry).

    Agents write these to record what they did / learned. ``path`` is a VIRTUAL
    folder path (e.g. ``research/auth-spike.md``) — folders are not real on disk,
    they are derived from the path. ``[[wikilinks]]`` and ``#hashtags`` in the
    body are parsed into MemoryLink edges + the ``tags`` array, which feed the
    web 3D reference graph.
    """

    __tablename__ = "memory_notes"
    __table_args__ = (
        UniqueConstraint("org_id", "path", name="uq_memory_note_org_path"),
        Index("ix_memory_notes_org_id", "org_id"),
        Index("ix_memory_notes_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # origin chat (no FK: chats may be pruned)

    path: Mapped[str] = mapped_column(String(512), nullable=False)  # virtual folder path incl. filename
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MemoryLink(Base):
    """A directed edge out of a memory note.

    - ``via='wikilink'`` → ``dst_note_id`` set when the ``[[target]]`` resolved to
      another note (else null + ``target_ref`` keeps the raw unresolved name).
    - ``via='tag'`` → ``target_ref`` holds the tag name; ``dst_note_id`` null
      (the web graph synthesises a node per distinct tag).
    """

    __tablename__ = "memory_links"
    __table_args__ = (
        Index("ix_memory_links_org_id", "org_id"),
        Index("ix_memory_links_src", "src_note_id"),
        Index("ix_memory_links_dst", "dst_note_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    src_note_id: Mapped[str] = mapped_column(String(36), ForeignKey("memory_notes.id", ondelete="CASCADE"), nullable=False)
    dst_note_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("memory_notes.id", ondelete="CASCADE"), nullable=True)
    via: Mapped[str] = mapped_column(String(20), nullable=False, default="wikilink")  # wikilink | tag
    target_ref: Mapped[str] = mapped_column(String(512), nullable=False)  # raw target (note title/path or tag name)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
