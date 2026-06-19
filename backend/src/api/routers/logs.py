"""Agent logs router — real-time per-agent logging with WS broadcast."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.pubsub import broadcast
from src.api.deps import get_current_user
from src.api.access import assert_chat_read_access
from src.models.user import User
from src.models.agent_log import AgentLog
from src.models.chat import Chat

router = APIRouter(prefix="/logs", tags=["logs"])


def utcnow():
    return datetime.now(timezone.utc)


class LogCreate(BaseModel):
    chat_id: str
    task_id: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    level: str = "info"   # debug | info | warn | error
    message: str
    data: dict | None = None


@router.post("", response_model=dict, status_code=201)
async def create_log(
    req: LogCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_chat_read_access(req.chat_id, current_user, db)
    entry = AgentLog(
        id=str(uuid.uuid4()),
        chat_id=req.chat_id,
        task_id=req.task_id,
        agent_id=req.agent_id,
        agent_name=req.agent_name,
        level=req.level,
        message=req.message,
        data=req.data,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    payload = {
        "id": entry.id,
        "chat_id": entry.chat_id,
        "task_id": entry.task_id,
        "agent_id": entry.agent_id,
        "agent_name": entry.agent_name,
        "level": entry.level,
        "message": entry.message,
        "data": entry.data,
        "created_at": entry.created_at.isoformat(),
    }
    await broadcast(req.chat_id, {"type": "log_entry", "log": payload})
    return payload


@router.get("", response_model=list[dict])
async def list_logs(
    chat_id: str = Query(...),
    limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_chat_read_access(chat_id, current_user, db)

    # Aggregate logs from the full conversation tree using a recursive CTE:
    # starting from this chat, follow task→sub_chat links to collect every
    # sub-chat in the tree (agents' execution contexts).
    result = await db.execute(
        text("""
            WITH RECURSIVE chat_tree AS (
                SELECT id FROM chats WHERE id = :chat_id
                UNION ALL
                SELECT c.id
                FROM chats c
                INNER JOIN tasks t ON t.sub_chat_id = c.id
                INNER JOIN chat_tree ct ON t.chat_id = ct.id
            )
            SELECT
                al.id, al.chat_id, al.task_id, al.agent_id,
                al.agent_name, al.level, al.message, al.data,
                al.created_at
            FROM agent_logs al
            WHERE al.chat_id IN (SELECT id FROM chat_tree)
            ORDER BY al.created_at DESC
            LIMIT :limit
        """),
        {"chat_id": chat_id, "limit": limit},
    )
    rows = result.mappings().all()
    return [
        {
            "id": row["id"],
            "chat_id": row["chat_id"],
            "task_id": row["task_id"],
            "agent_id": row["agent_id"],
            "agent_name": row["agent_name"],
            "level": row["level"],
            "message": row["message"],
            "data": row["data"],
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        }
        for row in rows
    ]
