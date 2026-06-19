from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from src.core.database import get_db
from src.api.deps import get_current_user
from src.models.user import User
from src.models.chat import Chat, Message
from src.api.routers.chats.access import _get_active_org_project_ids

router = APIRouter()


@router.get("/search")
async def search_chats(
    q: str = Query(..., min_length=2),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full-text search across all chat messages accessible to the current user."""
    if not q or len(q.strip()) < 2:
        return {"results": [], "total": 0, "query": q}

    org_project_ids = await _get_active_org_project_ids(current_user, db)

    # Accessible chats: own chats + chats in org projects
    accessible_chats_filter = or_(
        Chat.user_id == current_user.id,
        Chat.project_id.in_(org_project_ids) if org_project_ids else Chat.id.is_(None),
    )

    # Count total matches
    count_q = (
        select(func.count())
        .select_from(Message)
        .join(Chat, Chat.id == Message.chat_id)
        .where(accessible_chats_filter)
        .where(Chat.is_archived == False)  # noqa: E712
        .where(Message.role.in_(["user", "assistant"]))
        .where(
            func.to_tsvector("english", Message.content).op("@@")(
                func.plainto_tsquery("english", q.strip())
            )
        )
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Fetch page of results
    results_q = (
        select(
            Message.id.label("message_id"),
            Message.content.label("content"),
            Message.role,
            Message.created_at,
            Chat.id.label("chat_id"),
            Chat.title.label("chat_title"),
        )
        .join(Chat, Chat.id == Message.chat_id)
        .where(accessible_chats_filter)
        .where(Chat.is_archived == False)  # noqa: E712
        .where(Message.role.in_(["user", "assistant"]))
        .where(
            func.to_tsvector("english", Message.content).op("@@")(
                func.plainto_tsquery("english", q.strip())
            )
        )
        .order_by(Message.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )

    rows = (await db.execute(results_q)).all()

    return {
        "results": [
            {
                "chat_id": r.chat_id,
                "chat_title": r.chat_title or "Untitled",
                "message_id": r.message_id,
                "excerpt": r.content[:200],
                "role": r.role,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "query": q,
    }
