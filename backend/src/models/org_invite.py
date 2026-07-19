import uuid
import secrets
from datetime import datetime, timezone, timedelta
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def default_expires():
    return datetime.now(timezone.utc) + timedelta(days=7)


class OrgInvite(Base):
    __tablename__ = "org_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=lambda: secrets.token_urlsafe(32))
    role: Mapped[str] = mapped_column(String(50), default="member")
    # Optional binding to a specific person. Set when the invite is meant to
    # auto-create an account (e.g. the CLI zero-touch onboarding flow): the
    # redeem endpoint creates a passwordless user with this email/name and joins
    # them to the org. Left NULL for plain "join an existing account" web invites.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invited_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=default_expires)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    org: Mapped["Organization"] = relationship("Organization")  # noqa: F821
    invited_by: Mapped["User"] = relationship("User", foreign_keys=[invited_by_id])  # noqa: F821
