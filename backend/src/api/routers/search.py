"""Full-text search across chats and messages using Postgres tsvector."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db, get_active_org_id
from src.models.user import User
from src.models.chat import Chat, Message

router = APIRouter(prefix="/search", tags=["search"])

_MAX_RESULTS = 30
_SNIPPET_LEN = 200


def _snippet(content: str, query: str) -> str:
    """Return a short excerpt around the first query word match."""
    q = query.lower().split()[0] if query else ""
    idx = content.lower().find(q)
    if idx == -1:
        return content[:_SNIPPET_LEN]
    start = max(0, idx - 60)
    end = min(len(content), idx + 140)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return prefix + content[start:end] + suffix


@router.get("")
async def search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=_MAX_RESULTS),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search chat titles and message content for the current user's org."""
    org_id = await get_active_org_id(current_user, db)
    term = q.strip()
    ilike = f"%{term}%"

    # ── Chat title matches ─────────────────────────────────────────────────────
    chat_q = (
        select(Chat)
        .where(
            Chat.user_id == current_user.id,
            Chat.is_archived.isnot(True),
            Chat.title.ilike(ilike),
        )
        .order_by(Chat.updated_at.desc())
        .limit(limit)
    )
    chat_rows = (await db.execute(chat_q)).scalars().all()
    chat_hits = [
        {
            "type": "chat",
            "id": c.id,
            "title": c.title,
            "snippet": c.title,
            "url": f"/chat/{c.id}",
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in chat_rows
    ]

    # ── Message content matches ────────────────────────────────────────────────
    # Join to Chat so we can filter by user_id and get chat title
    msg_q = (
        select(Message, Chat.title, Chat.id.label("chat_id"))
        .join(Chat, Chat.id == Message.chat_id)
        .where(
            Chat.user_id == current_user.id,
            Chat.is_archived.isnot(True),
            Message.excluded.isnot(True),
            Message.role.in_(["user", "assistant"]),
            Message.content.ilike(ilike),
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    msg_rows = (await db.execute(msg_q)).all()
    msg_hits = [
        {
            "type": "message",
            "id": row.Message.id,
            "title": row.title,
            "snippet": _snippet(row.Message.content, term),
            "url": f"/chat/{row.chat_id}",
            "role": row.Message.role,
            "created_at": row.Message.created_at.isoformat() if row.Message.created_at else None,
            "chat_id": row.chat_id,
        }
        for row in msg_rows
    ]

    # Deduplicate chat hits already surfaced by title search
    chat_ids_in_title = {h["id"] for h in chat_hits}
    msg_hits_deduped = [h for h in msg_hits if h["chat_id"] not in chat_ids_in_title]

    results = (chat_hits + msg_hits_deduped)[:limit]
    return {"query": term, "results": results, "total": len(results)}
