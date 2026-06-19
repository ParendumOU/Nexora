"""Org- and user-scoped environment variables for tools.

Tools (marketplace connectors etc.) read credentials from env vars (e.g.
`STRIPE_SECRET_KEY`). Instead of forcing a server `.env`, users store those
values here, scoped to an **organization** (shared by the org) or a **user**
(personal). At tool-execution time the value is resolved org-first, then user.

Multiple rows may share the same `key` (e.g. a prod and a test
`STRIPE_SECRET_KEY`); each carries a unique `name` within its scope so the UI /
an agent can disambiguate. Values are encrypted at rest (Fernet).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class EnvVar(Base):
    __tablename__ = "environment_variables"
    __table_args__ = (
        # A given name is unique within an owner scope (org OR user).
        UniqueConstraint("scope", "org_id", "user_id", "name", name="uq_env_scope_owner_name"),
        Index("ix_env_org_key", "org_id", "key"),
        Index("ix_env_user_key", "user_id", "key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scope: Mapped[str] = mapped_column(String(10), nullable=False)  # "org" | "user"
    org_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)       # the real env var, e.g. STRIPE_SECRET_KEY
    name: Mapped[str] = mapped_column(String(120), nullable=False)      # unique label for disambiguation
    value_enc: Mapped[str] = mapped_column(Text, nullable=False)        # Fernet-encrypted value
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
