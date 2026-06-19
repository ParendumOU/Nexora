"""Append a structured note to the shared notes for the root chat."""
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.core.pubsub import broadcast
from src.models.chat import Chat, ChatNote


async def _resolve_root_chat(db, chat_id: str) -> Chat | None:
    r = await db.execute(select(Chat).where(Chat.id == chat_id))
    cur = r.scalar_one_or_none()
    visited: set[str] = set()
    while cur and cur.parent_chat_id and cur.id not in visited:
        visited.add(cur.id)
        r2 = await db.execute(select(Chat).where(Chat.id == cur.parent_chat_id))
        cur = r2.scalar_one_or_none()
    return cur


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    content = (args.get("content") or "").strip()
    if not content:
        return {"error": "content is required"}
    description = (args.get("heading") or args.get("description") or "").strip() or None

    async with AsyncSessionLocal() as db:
        root = await _resolve_root_chat(db, chat_id)
        if not root:
            return {"error": f"Chat {chat_id} not found"}

        note = ChatNote(
            id=str(uuid.uuid4()),
            chat_id=root.id,
            content=content,
            description=description,
            author=agent_name or "Agent",
            source_chat_id=chat_id if chat_id != root.id else None,
        )
        db.add(note)
        await db.commit()
        await db.refresh(note)
        root_id = root.id
        note_id = note.id

    await broadcast(root_id, {
        "type": "chat_notes_updated",
        "chat_id": root_id,
        "action": "created",
        "note_id": note_id,
    })
    return {"data": {"chat_id": root_id, "note_id": note_id}}
