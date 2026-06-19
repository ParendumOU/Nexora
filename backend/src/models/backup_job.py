import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class BackupJob(Base):
    """Tracks an async full-platform backup export job (mirrors the GDPR export pattern).

    Doubles as a *migration* job (``kind="migrate"``): the same backup is built, then pushed
    straight into a target instance's import endpoint instead of being offered for download —
    the one-step "upgrade community → Cloud without losing anything" flow.
    """
    __tablename__ = "backup_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="export")  # export | migrate
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="instance")  # instance | org
    org_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list for org scope
    include_vectors: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|running|done|failed
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # migrate: target instance root
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # migrate: JSON import summary from target
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
