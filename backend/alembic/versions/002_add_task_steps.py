"""add task steps table

Revision ID: 002
Revises: 001
Create Date: 2025-01-13

"""
from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if table already exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "task_steps" not in inspector.get_table_names():
        op.create_table(
            "task_steps",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("task_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("label", sa.String(500), nullable=False),
            sa.Column("status", sa.String(50), nullable=False, default="pending"),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("result_data", sa.JSON, nullable=False, default=dict),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_task_steps_task_id", "task_steps", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_steps_task_id", table_name="task_steps")
    op.drop_table("task_steps")
