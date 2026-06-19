"""Add agent_overrides to tasks for per-task capability grants."""
import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("agent_overrides", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "agent_overrides")
