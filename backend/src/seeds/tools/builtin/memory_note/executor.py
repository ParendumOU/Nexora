"""memory_note — write/append/read/list structured markdown memory notes."""
import logging
from sqlalchemy import select, func
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.agent import Agent
from src.models.memory_note import MemoryNote, MemoryLink
from src.services import memory_notes as svc

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {"write", "append", "read", "list"}


async def _resolve_org_and_user(db, chat_id: str, agent_id: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (org_id, user_id, agent_id). org_id is derived from the agent (chats have no org_id)."""
    user_id = None
    rc = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if rc:
        user_id = rc.user_id
        if not agent_id and rc.agent_id:
            agent_id = rc.agent_id
    org_id = None
    if agent_id:
        ag = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if ag:
            org_id = ag.org_id
    return org_id, user_id, agent_id


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    action = (args.get("action") or "").strip().lower()
    if action not in _VALID_ACTIONS:
        return {"error": f"action must be one of: {', '.join(sorted(_VALID_ACTIONS))}"}

    async with AsyncSessionLocal() as db:
        org_id, user_id, agent_id = await _resolve_org_and_user(db, chat_id, agent_id)
    if not org_id:
        return {"error": "Could not resolve org for this chat"}

    if action == "list":
        return await _list(args, org_id)
    if action == "read":
        return await _read(args, org_id)

    # write | append
    body = (args.get("body") or "").strip()
    if not body:
        return {"error": "body is required for write/append"}
    title = (args.get("title") or "").strip()
    path = (args.get("path") or "").strip() or None
    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    if action == "append":
        # merge into existing note at path (or by title); prepend existing body
        async with AsyncSessionLocal() as db:
            existing = None
            if path:
                norm = svc.normalize_path(path, title or path)
                existing = (await db.execute(
                    select(MemoryNote).where(MemoryNote.org_id == org_id, MemoryNote.path == norm)
                )).scalar_one_or_none()
            if existing:
                body = f"{existing.body_md.rstrip()}\n\n{body}"
                title = title or existing.title

    if not title:
        return {"error": "title is required for write (or an existing note to append to)"}

    result = await svc.upsert_note(
        org_id=org_id, title=title, body_md=body, path=path,
        agent_id=agent_id, user_id=user_id, chat_id=chat_id, extra_tags=tags,
    )
    return {"data": result}


async def _read(args: dict, org_id: str) -> dict:
    path = (args.get("path") or "").strip()
    note_id = (args.get("id") or "").strip()
    if not path and not note_id:
        return {"error": "read requires path or id"}
    async with AsyncSessionLocal() as db:
        q = select(MemoryNote).where(MemoryNote.org_id == org_id)
        if note_id:
            q = q.where(MemoryNote.id == note_id)
        else:
            norm = svc.normalize_path(path, path)
            q = q.where(func.lower(MemoryNote.path) == norm.lower())
        note = (await db.execute(q.limit(1))).scalar_one_or_none()
        if not note:
            return {"error": "Note not found"}
        links = (await db.execute(
            select(MemoryLink.via, MemoryLink.target_ref).where(MemoryLink.src_note_id == note.id)
        )).all()
    return {"data": {
        "id": note.id, "path": note.path, "title": note.title,
        "body": note.body_md, "tags": note.tags or [],
        "links": [{"via": v, "target": t} for v, t in links],
    }}


async def _list(args: dict, org_id: str) -> dict:
    folder = (args.get("folder") or "").strip().strip("/")
    tag = (args.get("tag") or "").strip().lower()
    search = (args.get("search") or "").strip().lower()
    limit = min(int(args.get("limit") or 30), 100)

    async with AsyncSessionLocal() as db:
        q = select(MemoryNote).where(MemoryNote.org_id == org_id)
        if folder:
            q = q.where(MemoryNote.path.ilike(f"{folder}/%"))
        q = q.order_by(MemoryNote.updated_at.desc()).limit(limit * 3)
        rows = (await db.execute(q)).scalars().all()

    results = []
    for n in rows:
        if tag and tag not in [t.lower() for t in (n.tags or [])]:
            continue
        if search and search not in n.title.lower() and search not in (n.body_md or "").lower():
            continue
        results.append({
            "id": n.id, "path": n.path, "title": n.title, "tags": n.tags or [],
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
        })
        if len(results) >= limit:
            break
    return {"data": {"notes": results, "count": len(results)}}
