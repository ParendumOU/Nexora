"""Add health tracking columns to providers table.

Revision ID: 035
Revises: 034
Create Date: 2026-05-30
"""
import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("providers")}

    if "last_error" not in existing:
        op.add_column("providers", sa.Column("last_error", sa.Text, nullable=True))
    if "last_error_at" not in existing:
        op.add_column("providers", sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True))
    if "last_used_at" not in existing:
        op.add_column("providers", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("providers", "last_used_at")
    op.drop_column("providers", "last_error_at")
    op.drop_column("providers", "last_error")
