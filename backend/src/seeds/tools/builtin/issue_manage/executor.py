import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.project import Project
from src.models.agent import Agent
from src.models.issue import Issue, IssueComment, ISSUE_STATUSES, ISSUE_PRIORITIES
from src.models.user import User
from src.core.pubsub import broadcast


async def _resolve_org_from_context(chat_rec, agent_id, db):
    org_id = None
    project_id = None

    if chat_rec and chat_rec.project_id:
        r = await db.execute(select(Project).where(Project.id == chat_rec.project_id))
        proj = r.unique().scalar_one_or_none()
        if proj:
            project_id = proj.id
            org_id = proj.org_id

    if not org_id and chat_rec and chat_rec.user_id:
        r = await db.execute(select(User.active_org_id).where(User.id == chat_rec.user_id))
        row = r.first()
        if row:
            org_id = row[0]

    if not org_id and agent_id:
        r = await db.execute(select(Agent).where(Agent.id == agent_id))
        ag = r.scalar_one_or_none()
        if ag:
            org_id = ag.org_id

    return org_id, project_id


async def _action_create(args, chat_id, agent_id, agent_name, db, chat_rec):
    # Coerce scalar args — a weak model may send an int for a string column (title,
    # project_id) which asyncpg rejects ("expected str, got int").
    from src.services.agent_tools.coerce import to_str, to_list
    title = to_str(args.get("title"))
    if not title:
        return {"error": "title is required"}

    org_id, resolved_project_id = await _resolve_org_from_context(chat_rec, agent_id, db)
    project_id = to_str(args.get("project_id")) or resolved_project_id

    if not org_id or not project_id:
        return {"error": "Could not resolve org_id/project_id. Provide project_id explicitly."}

    priority = args.get("priority", "medium")
    if priority not in ISSUE_PRIORITIES:
        priority = "medium"

    from src.services.agent_tools import _resolve_agent_id
    resolved_agent_id = await _resolve_agent_id(args.get("assigned_agent_id"), db)

    issue = Issue(
        id=str(uuid.uuid4()),
        org_id=org_id,
        project_id=project_id,
        title=title,
        description=to_str(args.get("description")),
        priority=priority,
        labels=to_list(args.get("labels")),
        assigned_agent_id=resolved_agent_id,
        reporter_agent_id=agent_id,
    )
    db.add(issue)
    await db.commit()
    await db.refresh(issue)
    result = {"id": issue.id, "project_id": issue.project_id,
              "title": issue.title, "status": issue.status, "priority": issue.priority}

    await broadcast(chat_id, {"type": "issue_created", "issue": result})
    return {"data": result}


async def _action_update(args, chat_id, agent_id, agent_name, db):
    issue_id = args.get("issue_id")
    if not issue_id:
        return {"error": "issue_id is required"}

    r = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = r.scalar_one_or_none()
    if not issue:
        return {"error": f"Issue {issue_id} not found"}

    from src.services.agent_tools.coerce import to_str, to_list
    if "title" in args and args["title"]:
        issue.title = to_str(args["title"])
    if "description" in args:
        issue.description = to_str(args["description"])
    if "status" in args:
        status = args["status"]
        if status in ISSUE_STATUSES:
            issue.status = status
            if status == "closed" and not issue.closed_at:
                issue.closed_at = datetime.now(timezone.utc)
            elif status != "closed":
                issue.closed_at = None
    if "priority" in args and args["priority"] in ISSUE_PRIORITIES:
        issue.priority = args["priority"]
    if "labels" in args:
        issue.labels = to_list(args["labels"])
    if "assigned_agent_id" in args:
        from src.services.agent_tools import _resolve_agent_id
        issue.assigned_agent_id = await _resolve_agent_id(args["assigned_agent_id"], db)

    await db.commit()
    await db.refresh(issue)
    result = {"id": issue.id, "title": issue.title,
              "status": issue.status, "priority": issue.priority}

    await broadcast(chat_id, {"type": "issue_updated", "issue": result})
    return {"data": result}


async def _action_comment(args, chat_id, agent_id, agent_name, db):
    issue_id = args.get("issue_id")
    content = args.get("content")
    if not issue_id or not content:
        return {"error": "issue_id and content are required"}

    r = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = r.scalar_one_or_none()
    if not issue:
        return {"error": f"Issue {issue_id} not found"}

    comment = IssueComment(
        id=str(uuid.uuid4()),
        issue_id=issue_id,
        author_agent_id=agent_id,
        content=content,
        metadata_=args.get("metadata", {}),
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    result = {
        "id": comment.id, "issue_id": issue_id,
        "author_agent_name": agent_name,
        "content": content[:100] + ("…" if len(content) > 100 else ""),
    }

    await broadcast(chat_id, {"type": "issue_comment_added", "comment": result})
    return {"data": result}


async def _action_list(args, chat_id, agent_id, agent_name, db, chat_rec):
    project_id = args.get("project_id")
    if not project_id and chat_rec and chat_rec.project_id:
        project_id = chat_rec.project_id

    if project_id:
        query = select(Issue).where(Issue.project_id == project_id)
    elif chat_rec:
        org_id, _ = await _resolve_org_from_context(chat_rec, agent_id, db)
        if not org_id:
            return {"error": "Could not determine org context."}
        query = select(Issue).where(Issue.org_id == org_id)
    else:
        return {"error": "No chat context available."}

    status_filter = args.get("status")
    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",")]
        query = query.where(Issue.status.in_(statuses))

    priority_filter = args.get("priority")
    if priority_filter:
        query = query.where(Issue.priority == priority_filter)

    agent_filter = args.get("assigned_to_agent")
    if agent_filter == "__unassigned__":
        query = query.where(Issue.assigned_agent_id == None)  # noqa: E711
    elif agent_filter:
        query = query.where(Issue.assigned_agent_id == agent_filter)

    query = query.order_by(Issue.created_at.desc()).limit(args.get("limit", 25))
    ir = await db.execute(query)
    issues = ir.scalars().all()

    result = [
        {
            "id": i.id, "title": i.title, "status": i.status,
            "priority": i.priority, "labels": i.labels or [],
            "project_id": i.project_id,
            "assigned_agent_id": i.assigned_agent_id,
            "description": (i.description or "")[:200],
        }
        for i in issues
    ]
    return {"data": result}


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    action = args.get("action")
    if not action:
        return {"error": "action is required (create | update | comment | list)"}

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat_rec = r.scalar_one_or_none()

        if action == "create":
            return await _action_create(args, chat_id, agent_id, agent_name, db, chat_rec)
        elif action == "update":
            return await _action_update(args, chat_id, agent_id, agent_name, db)
        elif action == "comment":
            return await _action_comment(args, chat_id, agent_id, agent_name, db)
        elif action == "list":
            return await _action_list(args, chat_id, agent_id, agent_name, db, chat_rec)
        else:
            return {"error": f"Unknown action '{action}'. Must be one of: create, update, comment, list"}
