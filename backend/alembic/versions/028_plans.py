"""plans and plan_steps tables

Revision ID: 028
Revises: 027
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    existing = inspect(conn).get_table_names()

    if "plans" not in existing:
        op.create_table(
            "plans",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True),
            sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id"), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_plans_chat_id", "plans", ["chat_id"])
        op.create_index("ix_plans_org_id", "plans", ["org_id"])
        op.create_index("ix_plans_status", "plans", ["status"])

    if "plan_steps" not in existing:
        op.create_table(
            "plan_steps",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("plan_id", sa.String(36), sa.ForeignKey("plans.id"), nullable=False),
            sa.Column("position", sa.Integer, nullable=False, server_default="0"),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("note", sa.Text, nullable=True),
            sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_plan_steps_plan_id", "plan_steps", ["plan_id"])


def downgrade() -> None:
    op.drop_table("plan_steps")
    op.drop_table("plans")
