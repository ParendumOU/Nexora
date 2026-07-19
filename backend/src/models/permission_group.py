import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class PermissionGroup(Base):
    """Org-scoped permission group.

    ``permissions`` holds the list of granted permission keys (see
    ``src.core.permissions.PERMISSION_CATALOG``). A member/viewer assigned to one
    or more groups is restricted to the union of those groups' grants; users with
    no group keep the default access for their role. Owners/admins always bypass.
    """
    __tablename__ = "permission_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Per-user usage caps (see src.core.permissions.merge_limits). Empty dict / 0 = unlimited.
    #   {token_budget, token_window_hours, max_concurrent_agents, max_provider_accounts}
    limits: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, server_default="{}")
    # Capability allowlists (see src.core.permissions.merge_capabilities). Empty list = unrestricted.
    #   {agent_ids[], skill_keys[], tool_keys[], persona_ids[], provider_ids[], chain_ids[],
    #    default_chain_id}
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    members: Mapped[list["PermissionGroupMember"]] = relationship(
        "PermissionGroupMember", back_populates="group", cascade="all, delete-orphan", lazy="select"
    )

    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_permission_groups_org_name"),)


class PermissionGroupMember(Base):
    __tablename__ = "permission_group_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("permission_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    group: Mapped["PermissionGroup"] = relationship("PermissionGroup", back_populates="members")

    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_permission_group_members_group_user"),)
