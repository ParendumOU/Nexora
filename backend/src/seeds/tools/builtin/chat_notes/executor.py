"""Chat notes tool — structured notes scratchpad for root chat + all subchats."""
import uuid
import logging
from sqlalchemy import select
from src.core import pubsub
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat, ChatNote

logger = logging.getLogger(__name__)


async def _resolve_root_chat_id(db, chat_id: str) -> str:
    visited: set[str] = set()
    current_id = chat_id
    while current_id and current_id not in visited:
        visited.add(current_id)
        r = await db.execute(select(Chat).where(Chat.id == current_id))
        chat = r.scalar_one_or_none()
        if not chat or not chat.parent_chat_id:
            return current_id
        current_id = chat.parent_chat_id
    return chat_id


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    action = (args.get("action") or "").strip().lower()
    if action not in ("read", "write", "append"):
        return {"error": "action must be one of: read, write, append"}

    async with AsyncSessionLocal() as db:
        root_id = await _resolve_root_chat_id(db, chat_id)

        r = await db.execute(select(Chat).where(Chat.id == root_id))
        root_chat = r.scalar_one_or_none()
        if not root_chat:
            return {"error": "Chat not found"}

        if action == "read":
            notes_r = await db.execute(
                select(ChatNote)
                .where(ChatNote.chat_id == root_id)
                .order_by(ChatNote.created_at)
            )
            notes = notes_r.scalars().all()
            notes_text = "\n\n".join(
                "## {} — {}{}\n\n{}".format(
                    n.author or "Unknown",
                    n.created_at.strftime("%Y-%m-%d %H:%M UTC"),
                    f"\n_{n.description}_" if n.description else "",
                    n.content,
                )
                for n in notes
            )
            return {"data": {"notes": notes_text, "count": len(notes), "chat_id": root_id}}

        content = (args.get("content") or "").strip()
        if not content:
            return {"error": "content is required for write/append"}

        description = (args.get("heading") or args.get("description") or "").strip() or None
        note = ChatNote(
            id=str(uuid.uuid4()),
            chat_id=root_id,
            content=content,
            description=description,
            author=agent_name or "Agent",
            source_chat_id=chat_id if chat_id != root_id else None,
        )
        db.add(note)
        await db.commit()
        await db.refresh(note)
        note_id = note.id

    await pubsub.broadcast(root_id, {
        "type": "chat_notes_updated",
        "chat_id": root_id,
        "action": "created",
        "note_id": note_id,
    })
    if root_id != chat_id:
        await pubsub.broadcast(chat_id, {
            "type": "chat_notes_updated",
            "chat_id": root_id,
            "action": "created",
            "note_id": note_id,
        })

    logger.info(f"[chat_notes] {action} on root={root_id} by agent={agent_name}")
    return {"data": {"action": action, "note_id": note_id, "chat_id": root_id}}
