import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Integer, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(50), default="apikey")
    credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    auth_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Per-account failover health (GitLab #216): durable state complementing the fast
    # Redis cooldown gate. state ∈ {healthy, cooling, exhausted}; cooling_until is the
    # durable skip-until (survives Redis flush/restart); consecutive_failures drives the
    # circuit (non-rate errors past the threshold mark the account exhausted).
    state: Mapped[str] = mapped_column(String(20), default="healthy", server_default="healthy", nullable=False)
    cooling_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Per-member governance: an account reserved to one member (exclusive ownership).
    # NULL = unassigned pool account, usable by members in 'all' mode. created_by_user_id
    # records who added the account, used by the 'own' provider mode.
    assigned_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    org: Mapped["Organization"] = relationship("Organization", back_populates="providers")  # noqa: F821


class ProviderChain(Base):
    __tablename__ = "provider_chains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["ProviderChainItem"]] = relationship(
        "ProviderChainItem", back_populates="chain",
        order_by="ProviderChainItem.position", lazy="joined",
        cascade="all, delete-orphan",
    )


class ProviderChainItem(Base):
    __tablename__ = "provider_chain_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chain_id: Mapped[str] = mapped_column(String(36), ForeignKey("provider_chains.id"), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    chain: Mapped["ProviderChain"] = relationship("ProviderChain", back_populates="items")
