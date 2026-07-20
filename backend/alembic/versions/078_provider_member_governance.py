"""Per-member provider-account governance

Adds exclusive provider-account ownership and a per-membership provider policy:
  - providers.assigned_user_id: the member an account is reserved to (NULL = pool).
  - providers.created_by_user_id: the member who added the account (for 'own' mode).
  - org_members.provider_mode: one of all|own|assigned (default 'all').

Defaults keep every install backward compatible: with the default mode and no
assignments, every member's usable pool equals all org accounts. Idempotent.

Revision ID: 078
Revises: 077
Create Date: 2026-07-20
"""
import sqlalchemy as sa
from alembic import op

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "providers" in tables:
        prov_cols = {c["name"] for c in insp.get_columns("providers")}
        if "assigned_user_id" not in prov_cols:
            op.add_column(
                "providers",
                sa.Column(
                    "assigned_user_id",
                    sa.String(36),
                    sa.ForeignKey("users.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
        if "created_by_user_id" not in prov_cols:
            op.add_column(
                "providers",
                sa.Column("created_by_user_id", sa.String(36), nullable=True),
            )

    if "org_members" in tables:
        member_cols = {c["name"] for c in insp.get_columns("org_members")}
        if "provider_mode" not in member_cols:
            op.add_column(
                "org_members",
                sa.Column(
                    "provider_mode",
                    sa.String(20),
                    nullable=False,
                    server_default="all",
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "org_members" in tables:
        member_cols = {c["name"] for c in insp.get_columns("org_members")}
        if "provider_mode" in member_cols:
            op.drop_column("org_members", "provider_mode")

    if "providers" in tables:
        prov_cols = {c["name"] for c in insp.get_columns("providers")}
        if "created_by_user_id" in prov_cols:
            op.drop_column("providers", "created_by_user_id")
        if "assigned_user_id" in prov_cols:
            op.drop_column("providers", "assigned_user_id")
