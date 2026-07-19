"""User.is_managed — managed (invited-employee) accounts

Adds a boolean flag to users. A managed account is created from an org invite:
it has no personal organization, is tied to exactly one org, and cannot switch,
create, join or leave organizations. Defaults to false so every existing account
stays a normal self-signup. Idempotent.

Revision ID: 077
Revises: 076
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "users" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "is_managed" not in cols:
        op.add_column(
            "users",
            sa.Column("is_managed", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "users" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "is_managed" in cols:
        op.drop_column("users", "is_managed")
