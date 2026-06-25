"""User notification delivery prefs (#212) + API key scoping (#177)

Adds users.notify_email / users.notify_telegram and
user_api_keys.scopes / user_api_keys.allowed_org_ids. Idempotent.

Revision ID: 070
Revises: 069
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def _cols(insp, table) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "users" in tables:
        ucols = _cols(insp, "users")
        if "notify_email" not in ucols:
            op.add_column("users", sa.Column("notify_email", sa.Boolean(), server_default="false", nullable=False))
        if "notify_telegram" not in ucols:
            op.add_column("users", sa.Column("notify_telegram", sa.Boolean(), server_default="false", nullable=False))

    if "user_api_keys" in tables:
        kcols = _cols(insp, "user_api_keys")
        if "scopes" not in kcols:
            op.add_column("user_api_keys", sa.Column("scopes", sa.JSON(), nullable=True))
        if "allowed_org_ids" not in kcols:
            op.add_column("user_api_keys", sa.Column("allowed_org_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    kcols = _cols(insp, "user_api_keys")
    if "allowed_org_ids" in kcols:
        op.drop_column("user_api_keys", "allowed_org_ids")
    if "scopes" in kcols:
        op.drop_column("user_api_keys", "scopes")
    ucols = _cols(insp, "users")
    if "notify_telegram" in ucols:
        op.drop_column("users", "notify_telegram")
    if "notify_email" in ucols:
        op.drop_column("users", "notify_email")
