"""Autonomy layer: durable goals + milestones, link tasks (GitLab #232)

Adds the `goals` and `milestones` tables (a persistent objective hierarchy above
ephemeral per-chat tasks) and two nullable links on `tasks` (`goal_id`,
`milestone_id`).

IDEMPOTENT: the backend runs `Base.metadata.create_all` at startup
(`core/lifespan/database.py`), so on a server that boots the new code before
migrating, `goals`/`milestones` already exist (created from the ORM) while
`tasks.goal_id`/`milestone_id` do not (create_all never ALTERs an existing table).
Every step is therefore guarded with the inspector so the migration completes
whether the objects exist or not, and records as revision 061 either way.

Revision ID: 061
Revises: 060
Create Date: 2026-06-24
"""
import sqlalchemy as sa
from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "goals" not in tables:
        op.create_table(
            "goals",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("parent_goal_id", sa.String(length=36), sa.ForeignKey("goals.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("owner_agent_id", sa.String(length=36), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("success_criteria", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
            sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
            sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "milestones" not in tables:
        op.create_table(
            "milestones",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("goal_id", sa.String(length=36), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("success_criteria", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )

    task_cols = {c["name"] for c in insp.get_columns("tasks")}
    if "goal_id" not in task_cols:
        op.add_column("tasks", sa.Column("goal_id", sa.String(length=36), nullable=True))
    if "milestone_id" not in task_cols:
        op.add_column("tasks", sa.Column("milestone_id", sa.String(length=36), nullable=True))

    task_idx = {i["name"] for i in insp.get_indexes("tasks")}
    if "ix_tasks_goal_id" not in task_idx:
        op.create_index("ix_tasks_goal_id", "tasks", ["goal_id"])
    if "ix_tasks_milestone_id" not in task_idx:
        op.create_index("ix_tasks_milestone_id", "tasks", ["milestone_id"])

    task_fks = {fk.get("name") for fk in insp.get_foreign_keys("tasks")}
    if "fk_tasks_goal_id" not in task_fks:
        op.create_foreign_key("fk_tasks_goal_id", "tasks", "goals", ["goal_id"], ["id"], ondelete="SET NULL")
    if "fk_tasks_milestone_id" not in task_fks:
        op.create_foreign_key("fk_tasks_milestone_id", "tasks", "milestones", ["milestone_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    task_fks = {fk.get("name") for fk in insp.get_foreign_keys("tasks")}
    if "fk_tasks_milestone_id" in task_fks:
        op.drop_constraint("fk_tasks_milestone_id", "tasks", type_="foreignkey")
    if "fk_tasks_goal_id" in task_fks:
        op.drop_constraint("fk_tasks_goal_id", "tasks", type_="foreignkey")
    task_idx = {i["name"] for i in insp.get_indexes("tasks")}
    if "ix_tasks_milestone_id" in task_idx:
        op.drop_index("ix_tasks_milestone_id", table_name="tasks")
    if "ix_tasks_goal_id" in task_idx:
        op.drop_index("ix_tasks_goal_id", table_name="tasks")
    task_cols = {c["name"] for c in insp.get_columns("tasks")}
    if "milestone_id" in task_cols:
        op.drop_column("tasks", "milestone_id")
    if "goal_id" in task_cols:
        op.drop_column("tasks", "goal_id")
    tables = set(insp.get_table_names())
    if "milestones" in tables:
        op.drop_table("milestones")
    if "goals" in tables:
        op.drop_table("goals")
