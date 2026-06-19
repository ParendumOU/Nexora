"""signup_invites table — platform-level registration invite tokens.

Revision ID: 032
Revises: 031
Create Date: 2026-05-30
"""
import sqlalchemy as sa
from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "signup_invites" not in existing_tables:
        op.create_table(
            "signup_invites",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("token", sa.String(64), nullable=False),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("used_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_signup_invites_token", "signup_invites", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_signup_invites_token", "signup_invites")
    op.drop_table("signup_invites")
