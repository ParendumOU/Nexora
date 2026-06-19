"""Issues CRUD router — GitLab-style issue tracking with comments."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.agent import Agent
from src.models.project import Project
from src.models.issue import Issue, IssueComment, ISSUE_STATUSES, ISSUE_PRIORITIES

router = APIRouter(prefix="/issues", tags=["issues"])


def utcnow():
    return datetime.now(timezone.utc)


async def _bg_push_issue(issue_id: str) -> None:
    from src.core.database import AsyncSessionLocal
    from src.services.git_issue_sync import push_issue
    async with AsyncSessionLocal() as db:
        try:
            await push_issue(issue_id, db)
        except Exception as exc:
            logger.warning(f"[git_sync] push_issue bg failed: {exc}")


async def _bg_close_issue(issue_id: str) -> None:
    from src.core.database import AsyncSessionLocal
    from src.services.git_issue_sync import close_issue_remote
    async with AsyncSessionLocal() as db:
        try:
            await close_issue_remote(issue_id, db)
        except Exception as exc:
            logger.warning(f"[git_sync] close_issue_remote bg failed: {exc}")


async def _bg_reopen_issue(issue_id: str) -> None:
    from src.core.database import AsyncSessionLocal
    from src.services.git_issue_sync import reopen_issue_remote
    async with AsyncSessionLocal() as db:
        try:
            await reopen_issue_remote(issue_id, db)
        except Exception as exc:
            logger.warning(f"[git_sync] reopen_issue_remote bg failed: {exc}")


# ── Schemas ───────────────────────────────────────────────────────────────────

class IssueCreate(BaseModel):
    project_id: str
    title: str
    description: str | None = None
    priority: str = "medium"
    labels: list[str] = []
    assigned_agent_id: str | None = None
    external_url: str | None = None
    external_ref: str | None = None


class IssueUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    labels: list[str] | None = None
    assigned_agent_id: str | None = None
    linked_task_id: str | None = None
    external_url: str | None = None
    external_ref: str | None = None


class CommentCreate(BaseModel):
    content: str
    metadata: dict = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _agent_name(db: AsyncSession, agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    r = await db.execute(select(Agent.name).where(Agent.id == agent_id))
    row = r.first()
    return row[0] if row else None


async def _user_name(db: AsyncSession, user_id: str | None) -> str | None:
    if not user_id:
        return None
    r = await db.execute(select(User.full_name).where(User.id == user_id))
    row = r.first()
    return row[0] if row else None


async def _issue_to_dict(issue: Issue, db: AsyncSession, include_comments: bool = False) -> dict:
    project_name: str | None = None
    r = await db.execute(select(Project.name).where(Project.id == issue.project_id))
    row = r.first()
    if row:
        project_name = row[0]

    # Comment count
    r2 = await db.execute(
        select(func.count()).select_from(IssueComment).where(IssueComment.issue_id == issue.id)
    )
    comment_count = r2.scalar() or 0

    result = {
        "id": issue.id,
        "org_id": issue.org_id,
        "project_id": issue.project_id,
        "project_name": project_name,
        "title": issue.title,
        "description": issue.description,
        "status": issue.status,
        "priority": issue.priority,
        "labels": issue.labels or [],
        "assigned_agent_id": issue.assigned_agent_id,
        "assigned_agent_name": await _agent_name(db, issue.assigned_agent_id),
        "reporter_agent_id": issue.reporter_agent_id,
        "reporter_agent_name": await _agent_name(db, issue.reporter_agent_id),
        "reporter_user_id": issue.reporter_user_id,
        "reporter_user_name": await _user_name(db, issue.reporter_user_id),
        "linked_task_id": issue.linked_task_id,
        "external_url": issue.external_url,
        "external_ref": issue.external_ref,
        "comment_count": comment_count,
        "created_at": issue.created_at.isoformat(),
        "updated_at": issue.updated_at.isoformat(),
        "closed_at": issue.closed_at.isoformat() if issue.closed_at else None,
    }

    if include_comments:
        r3 = await db.execute(
            select(IssueComment)
            .where(IssueComment.issue_id == issue.id)
            .order_by(IssueComment.created_at)
        )
        comments = []
        for c in r3.scalars().all():
            comments.append({
                "id": c.id,
                "issue_id": c.issue_id,
                "author_agent_id": c.author_agent_id,
                "author_agent_name": await _agent_name(db, c.author_agent_id),
                "author_user_id": c.author_user_id,
                "author_user_name": await _user_name(db, c.author_user_id),
                "content": c.content,
                "metadata": c.metadata_ or {},
                "created_at": c.created_at.isoformat(),
            })
        result["comments"] = comments

    return result


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_issues(
    project_id: str | None = Query(None),
    status: str | None = Query(None),
    priority: str | None = Query(None),
    assigned_agent_id: str | None = Query(None),
    label: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    query = select(Issue).where(Issue.org_id == org_id)

    if project_id:
        query = query.where(Issue.project_id == project_id)
    if status:
        statuses = [s.strip() for s in status.split(",")]
        query = query.where(Issue.status.in_(statuses))
    if priority:
        priorities = [p.strip() for p in priority.split(",")]
        query = query.where(Issue.priority.in_(priorities))
    if assigned_agent_id:
        query = query.where(Issue.assigned_agent_id == assigned_agent_id)
    if search:
        query = query.where(Issue.title.ilike(f"%{search}%"))

    # Count total before pagination
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(Issue.created_at.desc()).offset(offset).limit(limit)
    r = await db.execute(query)
    issues = r.scalars().all()

    # Label filtering in Python (JSON arrays aren't easily filterable in SQL)
    if label:
        issues = [i for i in issues if label in (i.labels or [])]

    return {
        "items": [await _issue_to_dict(i, db) for i in issues],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("", status_code=201)
async def create_issue(
    req: IssueCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)

    # Verify project belongs to org
    r = await db.execute(
        select(Project).where(Project.id == req.project_id, Project.org_id == org_id)
    )
    if not r.unique().scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    if req.priority not in ISSUE_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {sorted(ISSUE_PRIORITIES)}")

    issue = Issue(
        id=str(uuid.uuid4()),
        org_id=org_id,
        project_id=req.project_id,
        title=req.title,
        description=req.description,
        priority=req.priority,
        labels=req.labels,
        assigned_agent_id=req.assigned_agent_id,
        reporter_user_id=current_user.id,
        external_url=req.external_url,
        external_ref=req.external_ref,
    )
    db.add(issue)
    await db.commit()
    await db.refresh(issue)
    asyncio.create_task(_bg_push_issue(issue.id))
    return await _issue_to_dict(issue, db)


@router.get("/{issue_id}")
async def get_issue(
    issue_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Issue).where(Issue.id == issue_id, Issue.org_id == org_id)
    )
    issue = r.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return await _issue_to_dict(issue, db, include_comments=True)


@router.patch("/{issue_id}")
async def update_issue(
    issue_id: str,
    req: IssueUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Issue).where(Issue.id == issue_id, Issue.org_id == org_id)
    )
    issue = r.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if req.title is not None:
        issue.title = req.title
    if req.description is not None:
        issue.description = req.description
    prev_status = issue.status
    if req.status is not None:
        if req.status not in ISSUE_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {sorted(ISSUE_STATUSES)}")
        issue.status = req.status
        if req.status == "closed" and not issue.closed_at:
            issue.closed_at = utcnow()
        elif req.status != "closed":
            issue.closed_at = None
    if req.priority is not None:
        if req.priority not in ISSUE_PRIORITIES:
            raise HTTPException(status_code=422, detail=f"priority must be one of {sorted(ISSUE_PRIORITIES)}")
        issue.priority = req.priority
    if req.labels is not None:
        issue.labels = req.labels
    if req.assigned_agent_id is not None:
        issue.assigned_agent_id = req.assigned_agent_id or None
    if req.linked_task_id is not None:
        issue.linked_task_id = req.linked_task_id or None
    if req.external_url is not None:
        issue.external_url = req.external_url or None
    if req.external_ref is not None:
        issue.external_ref = req.external_ref or None

    await db.commit()
    await db.refresh(issue)
    if req.status is not None and req.status != prev_status:
        if req.status == "closed":
            asyncio.create_task(_bg_close_issue(issue.id))
        elif prev_status == "closed":
            asyncio.create_task(_bg_reopen_issue(issue.id))
    return await _issue_to_dict(issue, db)


@router.delete("/{issue_id}", status_code=204)
async def delete_issue(
    issue_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Issue).where(Issue.id == issue_id, Issue.org_id == org_id)
    )
    issue = r.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    await db.delete(issue)
    await db.commit()


# ── Comments ──────────────────────────────────────────────────────────────────

@router.get("/{issue_id}/comments")
async def list_comments(
    issue_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    # Verify issue access
    r = await db.execute(
        select(Issue).where(Issue.id == issue_id, Issue.org_id == org_id)
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Issue not found")

    r2 = await db.execute(
        select(IssueComment)
        .where(IssueComment.issue_id == issue_id)
        .order_by(IssueComment.created_at)
    )
    comments = []
    for c in r2.scalars().all():
        comments.append({
            "id": c.id,
            "issue_id": c.issue_id,
            "author_agent_id": c.author_agent_id,
            "author_agent_name": await _agent_name(db, c.author_agent_id),
            "author_user_id": c.author_user_id,
            "author_user_name": await _user_name(db, c.author_user_id),
            "content": c.content,
            "metadata": c.metadata_ or {},
            "created_at": c.created_at.isoformat(),
        })
    return comments


@router.post("/{issue_id}/comments", status_code=201)
async def create_comment(
    issue_id: str,
    req: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Issue).where(Issue.id == issue_id, Issue.org_id == org_id)
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Issue not found")

    comment = IssueComment(
        id=str(uuid.uuid4()),
        issue_id=issue_id,
        author_user_id=current_user.id,
        content=req.content,
        metadata_=req.metadata,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return {
        "id": comment.id,
        "issue_id": comment.issue_id,
        "author_agent_id": None,
        "author_agent_name": None,
        "author_user_id": comment.author_user_id,
        "author_user_name": current_user.full_name,
        "content": comment.content,
        "metadata": comment.metadata_ or {},
        "created_at": comment.created_at.isoformat(),
    }


@router.delete("/{issue_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    issue_id: str,
    comment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Issue).where(Issue.id == issue_id, Issue.org_id == org_id)
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Issue not found")

    r2 = await db.execute(
        select(IssueComment).where(
            IssueComment.id == comment_id,
            IssueComment.issue_id == issue_id,
        )
    )
    comment = r2.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    await db.delete(comment)
    await db.commit()
