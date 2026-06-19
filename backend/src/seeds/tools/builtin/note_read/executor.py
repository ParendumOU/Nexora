"""Read the shared notes for the current chat tree (root chat)."""
from sqlalchemy import select, desc
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat, ChatNote


async def _resolve_root(chat_id: str) -> Chat | None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == chat_id))
        cur = r.scalar_one_or_none()
        visited: set[str] = set()
        while cur and cur.parent_chat_id and cur.id not in visited:
            visited.add(cur.id)
            r2 = await db.execute(select(Chat).where(Chat.id == cur.parent_chat_id))
            cur = r2.scalar_one_or_none()
        return cur


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == chat_id))
        cur = r.scalar_one_or_none()
        if not cur:
            return {"error": f"Chat {chat_id} not found"}
        visited: set[str] = set()
        while cur and cur.parent_chat_id and cur.id not in visited:
            visited.add(cur.id)
            r2 = await db.execute(select(Chat).where(Chat.id == cur.parent_chat_id))
            cur = r2.scalar_one_or_none()
        root = cur

        notes_r = await db.execute(
            select(ChatNote)
            .where(ChatNote.chat_id == root.id)
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
    return {
        "data": {
            "notes": notes_text,
            "count": len(notes),
            "chat_id": root.id,
        }
    }
