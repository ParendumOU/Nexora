"""Add retry/recovery columns to tasks (retry_count, retry_after, last_error)."""
import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [c["name"] for c in inspector.get_columns("tasks")]
    if "retry_count" not in existing:
        op.add_column(
            "tasks",
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "retry_after" not in existing:
        op.add_column(
            "tasks",
            sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        )
    if "last_error" not in existing:
        op.add_column(
            "tasks",
            sa.Column("last_error", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    for col in ("last_error", "retry_after", "retry_count"):
        try:
            op.drop_column("tasks", col)
        except Exception:
            pass
