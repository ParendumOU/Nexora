import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Boolean, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_emoji: Mapped[str | None] = mapped_column(String(10), nullable=True)
    telegram_user_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    # A managed account is born from an org invite: no personal org, tied to exactly
    # one org, cannot switch/create/join/leave orgs. Normal self-signup stays False.
    is_managed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # #212: opt-in delivery of notifications via email / Telegram DM for events
    # missed while no real-time client was connected.
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    notify_telegram: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active_org_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True)
    # TOTP 2FA — secret encrypted with Fernet, backup_codes JSON array also encrypted
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    totp_backup_codes: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted JSON list
    # NexoraMarketplace personal API key (Fernet-encrypted)
    marketplace_api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # OAuth social login
    oauth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Email verification — is_verified defaults to True so existing users are unaffected
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    memberships: Mapped[list["OrgMember"]] = relationship("OrgMember", back_populates="user", lazy="select")  # noqa: F821
    chats: Mapped[list["Chat"]] = relationship("Chat", back_populates="user", lazy="select")  # noqa: F821
