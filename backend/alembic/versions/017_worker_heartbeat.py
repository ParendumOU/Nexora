"""Add worker_id and worker_heartbeat_at to tasks for distributed lock / crash recovery."""
import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [c["name"] for c in inspector.get_columns("tasks")]

    if "worker_id" not in existing:
        op.add_column("tasks", sa.Column("worker_id", sa.String(64), nullable=True))
    if "worker_heartbeat_at" not in existing:
        op.add_column(
            "tasks",
            sa.Column("worker_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    for col in ("worker_heartbeat_at", "worker_id"):
        try:
            op.drop_column("tasks", col)
        except Exception:
            pass
