"""Add missing FK indexes across all models to prevent full table scans."""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

_INDEXES = [
    # chats
    ("ix_chats_user_id",              "chats",               "user_id"),
    ("ix_chats_project_id",           "chats",               "project_id"),
    ("ix_chats_parent_chat_id",       "chats",               "parent_chat_id"),
    ("ix_chats_agent_id",             "chats",               "agent_id"),
    ("ix_chats_provider_chain_id",    "chats",               "provider_chain_id"),
    ("ix_chats_direct_provider_id",   "chats",               "direct_provider_id"),
    # messages
    ("ix_messages_chat_id",           "messages",            "chat_id"),
    ("ix_messages_agent_id",          "messages",            "agent_id"),
    # tasks
    ("ix_tasks_chat_id",              "tasks",               "chat_id"),
    ("ix_tasks_assigned_agent_id",    "tasks",               "assigned_agent_id"),
    ("ix_tasks_project_id",           "tasks",               "project_id"),
    ("ix_tasks_parent_id",            "tasks",               "parent_id"),
    ("ix_tasks_sub_chat_id",          "tasks",               "sub_chat_id"),
    # task_steps
    ("ix_task_steps_task_id",         "task_steps",          "task_id"),
    # agents
    ("ix_agents_org_id",              "agents",              "org_id"),
    # agent_logs
    ("ix_agent_logs_chat_id",         "agent_logs",          "chat_id"),
    ("ix_agent_logs_task_id",         "agent_logs",          "task_id"),
    # agent_memories
    ("ix_agent_memories_agent_id",    "agent_memories",      "agent_id"),
    ("ix_agent_memories_org_id",      "agent_memories",      "org_id"),
    # providers
    ("ix_providers_org_id",           "providers",           "org_id"),
    ("ix_provider_chains_org_id",     "provider_chains",     "org_id"),
    ("ix_provider_chain_items_chain_id", "provider_chain_items", "chain_id"),
    # org
    ("ix_org_members_org_id",         "org_members",         "org_id"),
    ("ix_org_members_user_id",        "org_members",         "user_id"),
    ("ix_org_invites_org_id",         "org_invites",         "org_id"),
    # projects
    ("ix_projects_org_id",            "projects",            "org_id"),
    ("ix_projects_pm_agent_id",       "projects",            "pm_agent_id"),
    # issues
    ("ix_issues_org_id",              "issues",              "org_id"),
    ("ix_issues_project_id",          "issues",              "project_id"),
    ("ix_issue_comments_issue_id",    "issue_comments",      "issue_id"),
    # workflows
    ("ix_agent_workflows_org_id",     "agent_workflows",     "org_id"),
    ("ix_agent_workflows_agent_id",   "agent_workflows",     "agent_id"),
    ("ix_agent_workflow_runs_workflow_id", "agent_workflow_runs", "workflow_id"),
    ("ix_agent_workflow_runs_chat_id",    "agent_workflow_runs", "chat_id"),
    # misc
    ("ix_personas_org_id",            "personas",            "org_id"),
    ("ix_skills_org_id",              "skills",              "org_id"),
    ("ix_tools_org_id",               "tools",               "org_id"),
    ("ix_mcp_servers_org_id",         "mcp_servers",         "org_id"),
    ("ix_model_profiles_org_id",      "model_profiles",      "org_id"),
    ("ix_git_credentials_org_id",     "git_credentials",     "org_id"),
    ("ix_integrations_org_id",        "integrations",        "org_id"),
    ("ix_users_active_org_id",        "users",               "active_org_id"),
    ("ix_project_memories_project_id","project_memories",    "project_id"),
    ("ix_project_memories_org_id",    "project_memories",    "org_id"),
]


def upgrade() -> None:
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(
        __import__("sqlalchemy").text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        )
    )}
    for name, table, column in _INDEXES:
        if name not in existing:
            op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, column in _INDEXES:
        try:
            op.drop_index(name, table_name=table)
        except Exception:
            pass
