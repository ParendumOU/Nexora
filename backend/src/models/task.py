import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


TASK_STATUSES = {"pending", "in_progress", "paused", "queued", "completed", "failed", "blocked", "dead"}


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Root context
    org_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=True, index=True
    )
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=True
    )
    # Tree structure
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)

    # Content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), default="pending")

    # Kanban fields
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    blocked_by: Mapped[list] = mapped_column(JSON, default=list)

    # Assignment
    assigned_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    model_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_chain_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("provider_chains.id"), nullable=True
    )

    # Checklist: [{id: str, item: str, done: bool}]
    checklist: Mapped[list] = mapped_column(JSON, default=list)

    # Optional sub-conversation spawned for this task
    sub_chat_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chats.id"), nullable=True
    )
    # When set, the sub-agent reuses this existing chat instead of creating a new one
    continue_chat_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    # Route this task's sub-agent to a specific model profile (overrides parent chain)
    model_profile_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )

    # Autonomy layer (#232): optional link to the goal/milestone this task advances.
    # Nullable — most tasks are still ad-hoc; goal-driven tasks set these so milestone
    # completion can roll up to goal progress.
    goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    milestone_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Per-task capability overrides set by the parent orchestrator at creation time.
    # Merged on top of the assigned agent's base config during execution only —
    # never persisted to the agent record itself.
    # Keys: additional_skills, additional_tools, additional_mcps, env_vars,
    #       system_prompt (full override), system_prompt_append (appended suffix)
    agent_overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    # Position in chat conversation (after which message this task was created)
    created_after_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id"), nullable=True
    )

    # Retry / recovery fields
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-task retry policy — overrides global settings when set.
    # Keys: max_retries (int), backoff_strategy ("exponential"|"linear"|"fixed"),
    #       backoff_base_seconds (int), escalation_agent_id (str|null),
    #       on_exhausted ("notify_orchestrator"|"fail_silent")
    retry_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Distributed execution tracking — updated every 30 s by the owning worker
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    children: Mapped[list["Task"]] = relationship(
        "Task",
        foreign_keys=[parent_id],
        back_populates="parent",
        lazy="select",
        order_by="Task.position",
    )
    parent: Mapped["Task | None"] = relationship(
        "Task", foreign_keys=[parent_id], back_populates="children", remote_side=[id]
    )
    assigned_agent: Mapped["Agent | None"] = relationship("Agent", foreign_keys=[assigned_agent_id])  # noqa: F821
    steps: Mapped[list["TaskStep"]] = relationship("TaskStep", back_populates="task", lazy="select", cascade="all, delete-orphan")  # noqa: F821


class TaskStep(Base):
    """Individual step/action within a task execution (e.g., tool calls by sub-agent)."""
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    
    # Step info
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # tool/action name
    label: Mapped[str] = mapped_column(String(500), nullable=False)  # human-readable label
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, running, success, failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Result data (for read-type tools)
    result_data: Mapped[dict] = mapped_column(JSON, default=dict)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="steps")
