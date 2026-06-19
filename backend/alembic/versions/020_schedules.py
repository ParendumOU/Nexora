"""Create schedules and schedule_runs tables."""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "schedules" not in existing_tables:
        op.create_table(
            "schedules",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("cron_expr", sa.String(100), nullable=True),
            sa.Column("interval_minutes", sa.Integer(), nullable=True),
            sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "schedule_runs" not in existing_tables:
        op.create_table(
            "schedule_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("schedule_id", sa.String(36), sa.ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="running"),
            sa.Column("triggered_by", sa.String(20), nullable=False, server_default="cron"),
            sa.Column("output", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("chat_id", sa.String(36), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("schedule_runs")
    op.drop_table("schedules")
