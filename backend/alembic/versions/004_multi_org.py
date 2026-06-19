"""multi-org: icon/color on org, active_org_id on user, org_invites table

Revision ID: 004
Revises: 003
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    table_names = inspector.get_table_names()

    if "organizations" in table_names:
        cols = [c["name"] for c in inspector.get_columns("organizations")]
        if "icon" not in cols:
            op.add_column("organizations", sa.Column("icon", sa.String(10), nullable=True))
        if "color" not in cols:
            op.add_column("organizations", sa.Column("color", sa.String(20), nullable=True))

    if "users" in table_names:
        cols = [c["name"] for c in inspector.get_columns("users")]
        if "active_org_id" not in cols:
            op.add_column("users", sa.Column("active_org_id", sa.String(36), nullable=True))

    if "org_invites" not in table_names:
        op.create_table(
            "org_invites",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("token", sa.String(64), nullable=False),
            sa.Column("role", sa.String(50), nullable=False, server_default="member"),
            sa.Column("invited_by_id", sa.String(36), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token", name="uq_org_invites_token"),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_org_invites_token", "org_invites", ["token"])


def downgrade() -> None:
    op.drop_index("ix_org_invites_token", table_name="org_invites")
    op.drop_table("org_invites")
    op.drop_column("users", "active_org_id")
    op.drop_column("organizations", "color")
    op.drop_column("organizations", "icon")
