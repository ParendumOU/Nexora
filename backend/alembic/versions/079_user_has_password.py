"""User.has_password — whether the account has a real, user-set password

CLI-onboarded (managed) accounts are created passwordless (a random unguessable
hash) so the employee can work from the terminal with no password. This flag lets
such a user set a password later to also sign in on the web. Existing accounts are
backfilled: managed accounts (passwordless at this point) get False, everyone else
True. Idempotent.

Revision ID: 079
Revises: 078
Create Date: 2026-07-20
"""
import sqlalchemy as sa
from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "users" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "has_password" not in cols:
        op.add_column(
            "users",
            sa.Column("has_password", sa.Boolean(), nullable=False, server_default="true"),
        )
        # Backfill: managed accounts were provisioned passwordless.
        if "is_managed" in cols:
            op.execute("UPDATE users SET has_password = false WHERE is_managed = true")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "users" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "has_password" in cols:
        op.drop_column("users", "has_password")
