from sqlalchemy import text
import logging

from src.core.database import engine, Base
from src.models import *  # noqa: F401, F403

logger = logging.getLogger(__name__)


async def startup_database():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as _e:
        if "pg_type" not in str(_e) and "already exists" not in str(_e):
            raise

    for stmt in [
            "ALTER TABLE providers ADD COLUMN IF NOT EXISTS auth_path VARCHAR(500)",
            # Agent capability columns
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS mcps JSON",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS tools JSON",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS env_vars JSON",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS max_subagents INTEGER DEFAULT 5",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS max_concurrency INTEGER DEFAULT 2",
            # Skill files
            "ALTER TABLE skills ADD COLUMN IF NOT EXISTS files JSON DEFAULT '{}'",
            # Backfill NULL agent columns
            "UPDATE agents SET tools = '[]' WHERE tools IS NULL",
            "UPDATE agents SET env_vars = '{}' WHERE env_vars IS NULL",
            "UPDATE agents SET mcps = '[]' WHERE mcps IS NULL",
            "UPDATE agents SET max_subagents = 5 WHERE max_subagents IS NULL",
            "UPDATE agents SET max_concurrency = 2 WHERE max_concurrency IS NULL",
            # Persona defaults
            "ALTER TABLE personas ADD COLUMN IF NOT EXISTS soul JSON DEFAULT '{}'",
            "ALTER TABLE personas ADD COLUMN IF NOT EXISTS default_skills JSON DEFAULT '[]'",
            "ALTER TABLE personas ADD COLUMN IF NOT EXISTS default_tools JSON DEFAULT '[]'",
            "ALTER TABLE personas ADD COLUMN IF NOT EXISTS default_mcps JSON DEFAULT '[]'",
            "ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS known_tools JSON DEFAULT '[]'",
            # Project capability columns
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS tools JSON",
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS mcps JSON",
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS env_vars JSON",
            "UPDATE projects SET tools = '[]' WHERE tools IS NULL",
            "UPDATE projects SET mcps = '[]' WHERE mcps IS NULL",
            "UPDATE projects SET env_vars = '{}' WHERE env_vars IS NULL",
            # Multi-org columns
            "ALTER TABLE provider_chain_items ADD COLUMN IF NOT EXISTS model_name VARCHAR(255)",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS excluded BOOLEAN DEFAULT FALSE",
            "UPDATE messages SET excluded = FALSE WHERE excluded IS NULL",
            "ALTER TABLE chats ADD COLUMN IF NOT EXISTS direct_provider_id VARCHAR(36)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS icon VARCHAR(10)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS color VARCHAR(20)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS is_personal BOOLEAN DEFAULT TRUE",
            "UPDATE organizations SET is_personal = TRUE WHERE is_personal IS NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS active_org_id VARCHAR(36)",
            # Integrations default flag
            "ALTER TABLE integrations ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE",
            # Tasks org attachment
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(id)",
            "CREATE INDEX IF NOT EXISTS ix_tasks_org_id ON tasks(org_id)",
            # Task sub-chat continuation (reuse existing sub-chat for follow-up tasks)
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS continue_chat_id VARCHAR(36)",
            # Telegram pending access requests
            """CREATE TABLE IF NOT EXISTS telegram_pending (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL,
                integration_id VARCHAR(36),
                tg_user_id VARCHAR(50) NOT NULL,
                tg_username VARCHAR(255),
                tg_display_name VARCHAR(255),
                code VARCHAR(10) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_tg_pending_org ON telegram_pending(org_id)",
            "CREATE INDEX IF NOT EXISTS ix_tg_pending_integration ON telegram_pending(integration_id)",
            # User profile extensions
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_emoji VARCHAR(10)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_user_id VARCHAR(50)",
            "CREATE INDEX IF NOT EXISTS ix_users_telegram_user_id ON users(telegram_user_id)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS notes TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS contact_info TEXT",
            # Backfill org_id for existing tasks via chat → project → org
            """
            UPDATE tasks t
            SET org_id = p.org_id
            FROM chats c
            JOIN projects p ON c.project_id = p.id
            WHERE t.chat_id = c.id
              AND t.org_id IS NULL
              AND p.org_id IS NOT NULL
            """,
            # Model profile per-task override
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS model_profile_id VARCHAR(36)",
            # Kanban board fields
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'medium'",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS blocked_by JSON DEFAULT '[]'",
            "UPDATE tasks SET priority = 'medium' WHERE priority IS NULL",
            "UPDATE tasks SET blocked_by = '[]' WHERE blocked_by IS NULL",
            # Schedules
            """CREATE TABLE IF NOT EXISTS schedules (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id),
                name VARCHAR(255) NOT NULL,
                description TEXT,
                cron_expr VARCHAR(100),
                interval_minutes INTEGER,
                agent_id VARCHAR(36) REFERENCES agents(id) ON DELETE SET NULL,
                prompt TEXT NOT NULL,
                is_active BOOLEAN DEFAULT FALSE,
                last_run_at TIMESTAMPTZ,
                next_run_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_schedules_org_id ON schedules(org_id)",
            """CREATE TABLE IF NOT EXISTS schedule_runs (
                id VARCHAR(36) PRIMARY KEY,
                schedule_id VARCHAR(36) NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
                org_id VARCHAR(36) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'running',
                triggered_by VARCHAR(20) NOT NULL DEFAULT 'cron',
                output TEXT,
                error TEXT,
                chat_id VARCHAR(36),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_schedule_runs_schedule_id ON schedule_runs(schedule_id)",
            # Project-scoped persistent memory
            """CREATE TABLE IF NOT EXISTS project_memories (
                id VARCHAR(36) PRIMARY KEY,
                project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id),
                agent_id VARCHAR(36) REFERENCES agents(id) ON DELETE SET NULL,
                type VARCHAR(20) NOT NULL DEFAULT 'fact',
                content TEXT NOT NULL,
                tags JSON DEFAULT '[]',
                priority INTEGER DEFAULT 3,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_project_memories_project ON project_memories(project_id)",
            "CREATE INDEX IF NOT EXISTS ix_project_memories_org ON project_memories(org_id)",
            # Distributed task execution tracking (migration 017)
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS worker_id VARCHAR(64)",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS worker_heartbeat_at TIMESTAMPTZ",
            # Chat soft-delete / archive (migration 018)
            "ALTER TABLE chats ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false",
    ]:
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SET lock_timeout = '5000ms'"))
                await conn.execute(text(stmt))
        except Exception:
            pass
