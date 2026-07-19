"""Permission groups — admin-managed user groups with granular permissions

Adds permission_groups (org-scoped named groups holding a JSON list of granted
permission keys) and permission_group_members (user assignments). Members and
viewers assigned to groups are restricted to the union of their groups' grants;
users without groups keep their role's default access. Idempotent.

Revision ID: 074
Revises: 073
Create Date: 2026-07-12
"""
import sqlalchemy as sa
from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "permission_groups" not in tables:
        op.create_table(
            "permission_groups",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("org_id", sa.String(length=36),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("org_id", "name", name="uq_permission_groups_org_name"),
        )
        op.create_index("ix_permission_groups_org_id", "permission_groups", ["org_id"])

    if "permission_group_members" not in tables:
        op.create_table(
            "permission_group_members",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("group_id", sa.String(length=36),
                      sa.ForeignKey("permission_groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(length=36),
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("group_id", "user_id", name="uq_permission_group_members_group_user"),
        )
        op.create_index("ix_permission_group_members_group_id", "permission_group_members", ["group_id"])
        op.create_index("ix_permission_group_members_user_id", "permission_group_members", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "permission_group_members" in tables:
        op.drop_table("permission_group_members")
    if "permission_groups" in tables:
        op.drop_table("permission_groups")
