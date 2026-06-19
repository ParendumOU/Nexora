"""Add retry_policy column to tasks table."""
import sqlalchemy as sa
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("tasks")}
    if "retry_policy" not in cols:
        op.add_column("tasks", sa.Column("retry_policy", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "retry_policy")
