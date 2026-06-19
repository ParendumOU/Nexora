"""Idempotent seed: creates default autonomous operation schedules."""
import logging
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.schedule import Schedule

logger = logging.getLogger(__name__)

# Fixed system IDs (same as seed_platform.py)
SYSTEM_ORG_ID = "00000000-0000-0000-0000-000000000010"
INFRA_AGENT_ID = "00000000-0000-0000-0000-000000000100"
SCRUM_MASTER_ID = "00000000-0000-0000-0000-000000000200"

# Fixed UUIDs for idempotency — never change these
_SCHEDULE_HEALTH_ID = "00000000-0000-0001-0000-000000000001"
_SCHEDULE_TRIAGE_ID = "00000000-0000-0001-0000-000000000002"
_SCHEDULE_SUMMARY_ID = "00000000-0000-0001-0000-000000000003"
_SCHEDULE_CLEANUP_ID = "00000000-0000-0001-0000-000000000004"
_SCHEDULE_STANDUP_ID = "00000000-0000-0001-0000-000000000005"
_SCHEDULE_RETRO_ID   = "00000000-0000-0001-0000-000000000006"

_DEFAULT_SCHEDULES = [
    {
        "id": _SCHEDULE_HEALTH_ID,
        "name": "Daily Platform Health Check",
        "description": "Checks Docker container status, backend logs for errors, and Redis/Postgres connectivity. Reports any anomalies.",
        "cron_expr": "0 8 * * *",  # 08:00 daily
        "agent_id": INFRA_AGENT_ID,
        "is_active": True,
        "prompt": (
            "Perform a daily platform health check. Do the following:\n\n"
            "1. Run `docker ps` to verify all containers (backend, frontend, postgres, redis, nginx) are Up and healthy.\n"
            "2. Check backend logs for ERROR or CRITICAL entries in the last 24 hours (`docker logs nexora-backend-1 --since 24h 2>&1 | grep -i 'error\\|critical' | tail -30`).\n"
            "3. Verify Redis is reachable and Postgres is accepting connections.\n"
            "4. Summarize findings: GREEN if all healthy, YELLOW if warnings, RED if any service is down.\n"
            "5. If RED: create a platform issue describing the problem.\n\n"
            "Keep the report concise. No action needed if everything is GREEN."
        ),
    },
    {
        "id": _SCHEDULE_TRIAGE_ID,
        "name": "Issue Auto-Triage",
        "description": "Scans for new unassigned issues in active GitLab projects and triages them (label, prioritize).",
        "interval_minutes": 120,  # every 2 hours
        "agent_id": INFRA_AGENT_ID,
        "is_active": True,
        "prompt": (
            "Perform automated issue triage for active GitLab projects.\n\n"
            "1. Use `gitlab_api` with action=`list_issues` to find recently opened issues (state=opened, created in last 2 hours) "
            "across the main active repositories.\n"
            "2. For each unassigned/unlabeled issue:\n"
            "   - Add appropriate labels (bug, enhancement, question, documentation) based on title/description\n"
            "   - Set priority label (critical, high, medium, low)\n"
            "3. If you cannot access GitLab (no credentials configured), skip silently and log that GitLab is not configured.\n"
            "4. Report a summary: N issues triaged, N skipped, N already labeled.\n\n"
            "Do not create duplicate labels. Do not modify issues that already have labels."
        ),
    },
    {
        "id": _SCHEDULE_SUMMARY_ID,
        "name": "Weekly Status Summary",
        "description": "Produces a weekly platform status report covering task activity, agent performance, and outstanding issues.",
        "cron_expr": "0 9 * * 1",  # Monday 09:00
        "agent_id": INFRA_AGENT_ID,
        "is_active": True,
        "prompt": (
            "Generate the weekly platform status summary for the Nexora system.\n\n"
            "Compile a structured report covering:\n\n"
            "**Platform Health**\n"
            "- Container and service status\n"
            "- Any incidents or restarts in the past week\n\n"
            "**Agent Activity**\n"
            "- How many tasks were created and completed\n"
            "- Any tasks that failed repeatedly (dead-letter queue)\n"
            "- Any agents that are inactive\n\n"
            "**Scheduled Jobs**\n"
            "- List active schedules and their last run status\n"
            "- Any schedules that failed\n\n"
            "**Recommendations**\n"
            "- Top 3 things that should be improved or investigated next week\n\n"
            "Save the report to chat_notes so all agents can reference it. "
            "Keep it concise — bullet points preferred."
        ),
    },
    {
        "id": _SCHEDULE_CLEANUP_ID,
        "name": "Weekly Memory Cleanup",
        "description": "Purges stale agent memories and cleans up orphaned sub-chats older than 30 days.",
        "cron_expr": "0 3 * * 0",  # Sunday 03:00
        "agent_id": INFRA_AGENT_ID,
        "is_active": True,
        "prompt": (
            "Perform weekly memory and data cleanup.\n\n"
            "1. Use `memory_manage` with action=`list` to find agent-scoped memories older than 30 days.\n"
            "   - Delete memories with type=`observation` or `note` older than 30 days.\n"
            "   - Preserve memories with type=`rule`, `preference`, or `critical`.\n"
            "2. Log a summary: N memories deleted, N preserved.\n\n"
            "Do not delete project-scoped memories — those are shared knowledge that should be maintained."
        ),
    },
    {
        "id": _SCHEDULE_STANDUP_ID,
        "name": "Daily Standup",
        "description": "Scrum Master broadcasts a standup request to all agents, collects replies, and publishes a structured summary.",
        "cron_expr": "30 9 * * *",  # 09:30 daily
        "agent_id": SCRUM_MASTER_ID,
        "is_active": True,
        "prompt": (
            "Run the daily standup.\n\n"
            "1. Broadcast a standup request to all active agents asking for: completed work, today's plan, blockers.\n"
            "2. Collect replies from agent inbox.\n"
            "3. Consolidate into a structured summary with sections: Status per agent, Blockers, Action items.\n"
            "4. Save the summary to chat_notes.\n"
            "5. For each reported blocker, use agent_notify with event_type=agent_blocked to alert relevant peers.\n"
            "6. Create tasks for any action items that need follow-up.\n\n"
            "Be brief and structured. Note non-responding agents neutrally."
        ),
    },
    {
        "id": _SCHEDULE_RETRO_ID,
        "name": "Weekly Retrospective",
        "description": "Scrum Master reads the week's standups and produces a retrospective on Monday morning.",
        "cron_expr": "0 9 * * 1",  # Monday 09:00 (before standup at 09:30)
        "agent_id": SCRUM_MASTER_ID,
        "is_active": True,
        "prompt": (
            "Run the weekly retrospective.\n\n"
            "1. Read chat_notes to gather this week's standup history.\n"
            "2. Identify patterns: recurring blockers, slow tasks, idle agents, repeated failures.\n"
            "3. Produce a retrospective with sections: What went well, What didn't, What to improve.\n"
            "4. Save to chat_notes under '## Retrospective — Week of [date]'.\n"
            "5. Store any recurring blocker patterns in project-scoped memory for future reference.\n\n"
            "Keep it concise and actionable. No blame — name patterns not individuals."
        ),
    },
]


async def seed_schedules() -> None:
    """Create default autonomous operation schedules if they don't already exist."""
    from src.services.scheduler import schedule_job

    async with AsyncSessionLocal() as db:
        created = 0
        activated = 0

        for spec in _DEFAULT_SCHEDULES:
            sid = spec["id"]
            r = await db.execute(select(Schedule).where(Schedule.id == sid))
            existing = r.scalar_one_or_none()
            if existing:
                # Ensure active schedules are registered with APScheduler after restart
                if existing.is_active:
                    try:
                        await schedule_job(
                            existing.id,
                            existing.cron_expr,
                            existing.interval_minutes,
                        )
                        activated += 1
                    except Exception as exc:
                        logger.debug(f"[seed_schedules] re-register {sid}: {exc}")
                continue

            sched = Schedule(
                id=sid,
                org_id=SYSTEM_ORG_ID,
                name=spec["name"],
                description=spec.get("description"),
                cron_expr=spec.get("cron_expr"),
                interval_minutes=spec.get("interval_minutes"),
                agent_id=spec["agent_id"],
                prompt=spec["prompt"],
                is_active=spec.get("is_active", False),
            )
            db.add(sched)
            await db.flush()
            created += 1

            if sched.is_active:
                try:
                    await schedule_job(sched.id, sched.cron_expr, sched.interval_minutes)
                    activated += 1
                except Exception as exc:
                    logger.warning(f"[seed_schedules] failed to activate {sid}: {exc}")

        await db.commit()

    if created or activated:
        logger.info(
            f"[seed_schedules] created={created} activated={activated} "
            f"(daily-health, 2h-triage, weekly-summary, weekly-cleanup, daily-standup, weekly-retro)"
        )
