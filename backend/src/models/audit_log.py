"""Structured audit log for sensitive operations (GitLab #178).

A durable, append-only record of security-relevant actions — member changes,
data export/import/migration, invite issuance, license-adjacent ops — so an
operator can answer "who did what, when, from where". Deliberately generic
(action + resource + free-form detail) so new call sites need no schema change.

Write via `services.audit.record_audit(...)`; never enforce/branch on these rows.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # org is nullable: some actions (superuser export-all) span orgs.
    org_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # actor: nullable so a system/automation action can be recorded too.
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    action: Mapped[str] = mapped_column(String(100), nullable=False)        # e.g. "org.member.add"
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)   # "org_member" | "backup" | …
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)         # action-specific extra context
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    __table_args__ = (
        Index("ix_audit_logs_org_created", "org_id", "created_at"),
    )
