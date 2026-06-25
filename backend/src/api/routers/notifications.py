import random
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.notification import Notification
from src.models.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str | None
    link: str | None
    read: bool
    created_at: datetime


async def push_notification(
    user_id: str,
    type: str,
    title: str,
    db: AsyncSession,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    """Utility to create a notification from anywhere in the backend."""
    notif = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
        created_at=datetime.now(timezone.utc),
    )
    db.add(notif)
    await db.flush()
    # #195: amortized retention — occasionally trim to the newest 500 per user so
    # the table doesn't grow unbounded (cheap: ~1 in 20 inserts pays the DELETE).
    if random.randint(1, 20) == 1:
        keep = (
            select(Notification.id)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(500)
        )
        await db.execute(
            delete(Notification).where(
                Notification.user_id == user_id, Notification.id.not_in(keep)
            )
        )
    # Push to the user's WebSocket channel so the bell updates instantly (no poll).
    try:
        from src.core import pubsub
        await pubsub.broadcast(f"user:{user_id}", {
            "type": "notification",
            "notification": {
                "id": notif.id, "type": notif.type, "title": notif.title,
                "body": notif.body, "link": notif.link, "read": False,
                "created_at": notif.created_at.isoformat(),
            },
        })
    except Exception:
        pass
    # #212: out-of-band delivery (email / Telegram) for opted-in users. Fire-and-
    # forget so it never blocks or breaks notification creation.
    try:
        import asyncio
        from src.services.notify_delivery import deliver_notification
        asyncio.create_task(deliver_notification(user_id, title, body, link))
    except Exception:
        pass
    return notif


@router.get("/", response_model=list[NotificationResponse])
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # #195: client-controlled paging (was a hardcoded limit=50 with no way to reach older items).
    q = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        q = q.where(Notification.read.is_(False))
    q = q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/{notif_id}/read", status_code=204)
async def mark_read(
    notif_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id, Notification.user_id == current_user.id)
        .values(read=True)
    )
    await db.commit()


@router.post("/read-all", status_code=204)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read == False)  # noqa: E712
        .values(read=True)
    )
    await db.commit()


@router.delete("/{notif_id}", status_code=204)
async def delete_notification(
    notif_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification)
        .where(Notification.id == notif_id, Notification.user_id == current_user.id)
    )
    notif = result.scalar_one_or_none()
    if notif:
        await db.delete(notif)
        await db.commit()
