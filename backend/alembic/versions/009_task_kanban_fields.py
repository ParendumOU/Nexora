"""Add priority and blocked_by kanban fields to tasks."""
import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
    )
    op.add_column(
        "tasks",
        sa.Column("blocked_by", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "blocked_by")
    op.drop_column("tasks", "priority")
