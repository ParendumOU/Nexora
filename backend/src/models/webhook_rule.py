import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class WebhookRule(Base):
    __tablename__ = "webhook_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), nullable=True)

    source: Mapped[str] = mapped_column(String(20), nullable=False)        # 'gitlab' | 'github' | 'custom'
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)   # 'issue.opened' | 'pipeline.failed' | …
    filter_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"labels": ["bug"], "branch": "main"}

    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False)
    task_title_template: Mapped[str] = mapped_column(Text, nullable=False)
    task_description_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Secret used to authenticate inbound custom webhook calls
    webhook_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    triggers: Mapped[list["WebhookRuleTrigger"]] = relationship(
        "WebhookRuleTrigger",
        back_populates="rule",
        cascade="all, delete-orphan",
        order_by="WebhookRuleTrigger.created_at.desc()",
    )


class WebhookRuleTrigger(Base):
    __tablename__ = "webhook_rule_triggers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_id: Mapped[str] = mapped_column(String(36), ForeignKey("webhook_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    rule: Mapped["WebhookRule"] = relationship("WebhookRule", back_populates="triggers")
