"""Issue and IssueComment models — GitLab-style issue tracking for projects."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


ISSUE_STATUSES = {"open", "in_progress", "review", "closed"}
ISSUE_PRIORITIES = {"critical", "high", "medium", "low"}


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )

    # Content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status & priority
    status: Mapped[str] = mapped_column(String(20), default="open")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    labels: Mapped[list] = mapped_column(JSON, default=list)

    # Assignment
    assigned_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )

    # Reporter (who created the issue — agent or user)
    reporter_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    reporter_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )

    # Bridge to existing Task system
    linked_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )

    # External issue tracking (GitHub/GitLab)
    external_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    comments: Mapped[list["IssueComment"]] = relationship(
        "IssueComment",
        back_populates="issue",
        cascade="all, delete-orphan",
        order_by="IssueComment.created_at",
    )
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id])
    reporter_agent = relationship("Agent", foreign_keys=[reporter_agent_id])
    reporter_user = relationship("User", foreign_keys=[reporter_user_id])
    linked_task = relationship("Task", foreign_keys=[linked_task_id])
    project = relationship("Project", foreign_keys=[project_id])


class IssueComment(Base):
    """Structured comment on an issue thread — from agents or users."""
    __tablename__ = "issue_comments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("issues.id"), nullable=False
    )

    # Author — one of these will be set
    author_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    author_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    # Relationships
    issue: Mapped["Issue"] = relationship("Issue", back_populates="comments")
    author_agent = relationship("Agent", foreign_keys=[author_agent_id])
    author_user = relationship("User", foreign_keys=[author_user_id])
