"""Project state aggregator — provides a structured summary of project health for PM agents."""
from __future__ import annotations

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.project import Project
from src.models.task import Task
from src.models.chat import Chat
from src.models.issue import Issue


async def get_project_state_summary(
    project_id: str,
    db: AsyncSession,
    *,
    max_issues: int = 15,
    max_tasks: int = 15,
) -> dict:
    """Build a structured summary of project health for injection into agent context.
    
    Returns a dict with:
        - issue_stats: counts by status
        - task_stats: counts by status
        - open_issues: list of open/in_progress issues (title, id, priority, status)
        - recent_tasks: list of recent tasks (title, id, status, agent)
    """
    # ── Issue statistics ──
    issue_status_r = await db.execute(
        select(Issue.status, func.count())
        .where(Issue.project_id == project_id)
        .group_by(Issue.status)
    )
    issue_stats = dict(issue_status_r.all())
    total_issues = sum(issue_stats.values())

    # ── Open/in-progress issues (details) ──
    open_issues_r = await db.execute(
        select(Issue)
        .where(
            Issue.project_id == project_id,
            Issue.status.in_(["open", "in_progress", "review"]),
        )
        .order_by(
            case(
                (Issue.priority == "critical", 0),
                (Issue.priority == "high", 1),
                (Issue.priority == "medium", 2),
                (Issue.priority == "low", 3),
                else_=4,
            )
        )
        .limit(max_issues)
    )
    open_issues = [
        {
            "id": i.id,
            "title": i.title,
            "status": i.status,
            "priority": i.priority,
            "labels": i.labels or [],
            "assigned_agent_id": i.assigned_agent_id,
        }
        for i in open_issues_r.scalars().all()
    ]

    # ── Task statistics ──
    # Get chat IDs for this project
    chat_ids_r = await db.execute(
        select(Chat.id).where(Chat.project_id == project_id)
    )
    chat_ids = [r for (r,) in chat_ids_r.all()]

    task_stats: dict = {}
    active_tasks: list[dict] = []
    if chat_ids:
        task_status_r = await db.execute(
            select(Task.status, func.count())
            .where(Task.chat_id.in_(chat_ids))
            .group_by(Task.status)
        )
        task_stats = dict(task_status_r.all())

        active_tasks_r = await db.execute(
            select(Task)
            .where(
                Task.chat_id.in_(chat_ids),
                Task.status.in_(["pending", "in_progress", "queued", "paused"]),
            )
            .order_by(Task.created_at.desc())
            .limit(max_tasks)
        )
        active_tasks = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "assigned_agent_id": t.assigned_agent_id,
            }
            for t in active_tasks_r.scalars().all()
        ]

    total_tasks = sum(task_stats.values())

    return {
        "issue_stats": issue_stats,
        "total_issues": total_issues,
        "open_issues": open_issues,
        "task_stats": task_stats,
        "total_tasks": total_tasks,
        "active_tasks": active_tasks,
    }


def format_project_state_for_prompt(state: dict) -> list[str]:
    """Format a project state dict into prompt lines for injection."""
    lines: list[str] = []

    # Issue summary
    issue_stats = state.get("issue_stats", {})
    total_issues = state.get("total_issues", 0)
    if total_issues > 0:
        lines.append("### Project Issues")
        parts = []
        for status in ["open", "in_progress", "review", "closed"]:
            count = issue_stats.get(status, 0)
            if count:
                parts.append(f"{count} {status.replace('_', ' ')}")
        lines.append(f"Total: {total_issues} — " + ", ".join(parts))
        lines.append("")

        open_issues = state.get("open_issues", [])
        if open_issues:
            lines.append("**Active issues** (use `issue_manage` action=update / action=comment to manage):")
            for i in open_issues:
                priority_marker = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}.get(i["priority"], "⚪")
                labels_text = f" [{', '.join(i['labels'][:3])}]" if i.get("labels") else ""
                assigned = f" → `{i['assigned_agent_id']}`" if i.get("assigned_agent_id") else ""
                lines.append(f"  {priority_marker} [{i['status'].upper()}] **{i['title']}** (id: `{i['id']}`){labels_text}{assigned}")
            lines.append("")
    else:
        lines += ["### Project Issues", "No issues tracked yet. Use `issue_manage` action=create to track problems, features, or improvements.", ""]

    # Task summary
    task_stats = state.get("task_stats", {})
    total_tasks = state.get("total_tasks", 0)
    if total_tasks > 0:
        lines.append("### Project Task Summary")
        parts = []
        for status in ["in_progress", "pending", "queued", "paused", "completed", "failed"]:
            count = task_stats.get(status, 0)
            if count:
                parts.append(f"{count} {status}")
        lines.append(f"Total: {total_tasks} — " + ", ".join(parts))

        active_tasks = state.get("active_tasks", [])
        if active_tasks:
            lines.append("")
            lines.append("**Active tasks:**")
            for t in active_tasks[:10]:
                assigned = f" → `{t['assigned_agent_id']}`" if t.get("assigned_agent_id") else ""
                lines.append(f"  - [{t['status'].upper()}] **{t['title']}** (id: `{t['id']}`){assigned}")
        lines.append("")

    return lines
