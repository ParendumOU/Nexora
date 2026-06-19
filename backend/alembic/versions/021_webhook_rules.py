"""Create webhook_rules and webhook_rule_triggers tables."""
import sqlalchemy as sa
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "webhook_rules" not in existing_tables:
        op.create_table(
            "webhook_rules",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("event_type", sa.String(100), nullable=False),
            sa.Column("filter_json", sa.JSON(), nullable=True),
            sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
            sa.Column("task_title_template", sa.Text(), nullable=False),
            sa.Column("task_description_template", sa.Text(), nullable=True),
            sa.Column("webhook_secret", sa.String(128), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "webhook_rule_triggers" not in existing_tables:
        op.create_table(
            "webhook_rule_triggers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("rule_id", sa.String(36), sa.ForeignKey("webhook_rules.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("event_type", sa.String(100), nullable=False),
            sa.Column("task_id", sa.String(36), nullable=True),
            sa.Column("payload_summary", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("webhook_rule_triggers")
    op.drop_table("webhook_rules")
