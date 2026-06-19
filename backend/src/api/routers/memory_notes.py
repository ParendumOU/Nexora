"""Memory-notes API — markdown memory vault + reference graph (web 3D view)."""
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.memory_note import MemoryNote, MemoryLink
from src.services import memory_notes as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/memory-notes", tags=["memory-notes"])


class NoteOut(BaseModel):
    id: str
    path: str
    title: str
    body_md: str
    tags: list
    agent_id: str | None
    user_id: str | None
    chat_id: str | None
    created_at: datetime
    updated_at: datetime


class NoteSummary(BaseModel):
    id: str
    path: str
    title: str
    tags: list
    agent_id: str | None
    updated_at: datetime


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1)
    body_md: str = ""
    path: str | None = None
    tags: list[str] = []


class NoteUpdate(BaseModel):
    title: str | None = None
    body_md: str | None = None
    path: str | None = None
    tags: list[str] | None = None


class NoteMove(BaseModel):
    path: str = Field(..., min_length=1)


def _full(n: MemoryNote) -> NoteOut:
    return NoteOut(
        id=n.id, path=n.path, title=n.title, body_md=n.body_md, tags=n.tags or [],
        agent_id=n.agent_id, user_id=n.user_id, chat_id=n.chat_id,
        created_at=n.created_at, updated_at=n.updated_at,
    )


async def _get_owned(db: AsyncSession, org_id: str, note_id: str) -> MemoryNote:
    n = (await db.execute(
        select(MemoryNote).where(MemoryNote.id == note_id, MemoryNote.org_id == org_id)
    )).scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=404, detail="Note not found")
    return n


@router.get("", response_model=list[NoteSummary])
async def list_notes(
    folder: str | None = Query(None),
    tag: str | None = Query(None),
    agent_id: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(500, le=2000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    q = select(MemoryNote).where(MemoryNote.org_id == org_id)
    if folder:
        q = q.where(MemoryNote.path.ilike(f"{folder.strip('/')}/%"))
    if agent_id:
        q = q.where(MemoryNote.agent_id == agent_id)
    q = q.order_by(MemoryNote.updated_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    tag_l = tag.lower() if tag else None
    search_l = search.lower() if search else None
    out: list[NoteSummary] = []
    for n in rows:
        if tag_l and tag_l not in [t.lower() for t in (n.tags or [])]:
            continue
        if search_l and search_l not in n.title.lower() and search_l not in (n.body_md or "").lower():
            continue
        out.append(NoteSummary(
            id=n.id, path=n.path, title=n.title, tags=n.tags or [],
            agent_id=n.agent_id, updated_at=n.updated_at,
        ))
    return out


@router.get("/graph")
async def memory_graph(
    agent_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Nodes (notes + tags) + links (note→note wikilinks, note→tag) for the 3D graph."""
    org_id = await get_active_org_id(current_user, db)
    nq = select(MemoryNote).where(MemoryNote.org_id == org_id)
    if agent_id:
        nq = nq.where(MemoryNote.agent_id == agent_id)
    notes = (await db.execute(nq)).scalars().all()
    note_ids = {n.id for n in notes}

    nodes: list[dict] = []
    links: list[dict] = []
    tag_nodes: dict[str, dict] = {}

    for n in notes:
        nodes.append({
            "id": n.id, "type": "note", "label": n.title, "path": n.path,
            "tags": n.tags or [], "agent_id": n.agent_id,
            "folder": n.path.rsplit("/", 1)[0] if "/" in n.path else "",
        })
        for t in (n.tags or []):
            tid = f"tag:{t.lower()}"
            tag_nodes.setdefault(tid, {"id": tid, "type": "tag", "label": f"#{t.lower()}"})
            links.append({"source": n.id, "target": tid, "type": "tag"})

    # note→note wikilink edges (only resolved ones, and only within the returned set)
    lq = select(MemoryLink).where(
        MemoryLink.org_id == org_id,
        MemoryLink.via == "wikilink",
        MemoryLink.dst_note_id.isnot(None),
    )
    for link in (await db.execute(lq)).scalars().all():
        if link.src_note_id in note_ids and link.dst_note_id in note_ids:
            links.append({"source": link.src_note_id, "target": link.dst_note_id, "type": "wikilink"})

    nodes.extend(tag_nodes.values())
    return {"nodes": nodes, "links": links}


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    return _full(await _get_owned(db, org_id, note_id))


@router.post("", response_model=NoteOut, status_code=201)
async def create_note(
    body: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    res = await svc.upsert_note(
        org_id=org_id, title=body.title, body_md=body.body_md, path=body.path,
        user_id=current_user.id, extra_tags=body.tags,
    )
    return _full(await _get_owned(db, org_id, res["id"]))


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: str,
    body: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    n = await _get_owned(db, org_id, note_id)
    await svc.upsert_note(
        org_id=org_id, note_id=n.id,
        title=body.title if body.title is not None else n.title,
        body_md=body.body_md if body.body_md is not None else n.body_md,
        path=body.path if body.path is not None else n.path,
        extra_tags=body.tags,  # None → keep hashtag-derived only
    )
    await db.refresh(n)  # service committed in its own session — reload request-session copy
    return _full(n)


@router.post("/{note_id}/move", response_model=NoteOut)
async def move_note(
    note_id: str,
    body: NoteMove,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    n = await _get_owned(db, org_id, note_id)
    await svc.upsert_note(
        org_id=org_id, note_id=n.id, title=n.title, body_md=n.body_md,
        path=body.path, extra_tags=n.tags or [],
    )
    await db.refresh(n)
    return _full(n)


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    n = await _get_owned(db, org_id, note_id)
    await db.delete(n)
    await db.commit()
