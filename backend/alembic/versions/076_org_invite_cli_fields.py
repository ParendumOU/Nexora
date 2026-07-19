"""Add email + full_name to org_invites (CLI zero-touch onboarding)

An org invite can now be bound to a specific person (email + optional display
name). The CLI-join redeem flow uses these to auto-create a passwordless account
into the inviting org when no user with that email exists yet. Both columns are
nullable so existing (web) invites are unaffected. Idempotent.

Revision ID: 076
Revises: 075
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def _cols(insp, table):
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "org_invites" not in set(insp.get_table_names()):
        return
    cols = _cols(insp, "org_invites")
    if "email" not in cols:
        op.add_column("org_invites", sa.Column("email", sa.String(length=255), nullable=True))
    if "full_name" not in cols:
        op.add_column("org_invites", sa.Column("full_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "org_invites" not in set(insp.get_table_names()):
        return
    cols = _cols(insp, "org_invites")
    if "full_name" in cols:
        op.drop_column("org_invites", "full_name")
    if "email" in cols:
        op.drop_column("org_invites", "email")
