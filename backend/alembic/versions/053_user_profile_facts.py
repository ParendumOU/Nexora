"""Add user_profile_facts table (keyed user-profile facts, patch-able).

Replaces the single-blob User.notes overwrite with discrete (key, value) rows
so the remember_user tool can patch one fact without clobbering the rest.
Existing User.notes values are backfilled as the reserved key 'freeform'.

Revision ID: 053
Revises: 052
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profile_facts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "key", name="uq_user_profile_fact_user_key"),
    )
    op.create_index("ix_user_profile_facts_user_id", "user_profile_facts", ["user_id"])

    # Backfill existing freeform notes as the reserved 'freeform' fact.
    op.execute(
        """
        INSERT INTO user_profile_facts (id, user_id, key, value, source, created_at, updated_at)
        SELECT
            md5(random()::text || clock_timestamp()::text),
            id, 'freeform', notes, 'legacy', now(), now()
        FROM users
        WHERE notes IS NOT NULL AND btrim(notes) <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_profile_facts_user_id", table_name="user_profile_facts")
    op.drop_table("user_profile_facts")
