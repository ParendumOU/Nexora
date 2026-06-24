"""Bind an agent to an optional ModelProfile (capability decoupling — GitLab #215)

Adds ``agents.model_profile_id`` (nullable FK → model_profiles, ON DELETE SET NULL).
When set, and the turn has no explicit per-message account/chain pick and no
chat/project chain, provider resolution routes through this profile so "which
model" is decoupled from the agent definition. Existing rows backfill to NULL
(unchanged behaviour — resolution falls through to the chat/org chain).

Revision ID: 059
Revises: 058
Create Date: 2026-06-24
"""
import sqlalchemy as sa
from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("model_profile_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_agents_model_profile_id",
        "agents",
        "model_profiles",
        ["model_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agents_model_profile_id", "agents", type_="foreignkey")
    op.drop_column("agents", "model_profile_id")
