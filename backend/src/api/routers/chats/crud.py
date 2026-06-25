import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_, text, func
from src.core.database import get_db
from src.api.deps import get_current_user
from src.models.user import User
from src.models.chat import Chat, ChatNote, Message
from src.models.project import Project
from src.models.agent import Agent
from src.core import pubsub
from src.api.routers.chats.access import _can_access_chat, _get_active_org_project_ids
from src.api.routers.chats.schemas import (
    ChatCreate, ChatResponse,
    ChatNoteCreate, ChatNoteUpdate, ChatNoteResponse, ChatNotesListResponse,
)

router = APIRouter()


@router.get("/", response_model=list[ChatResponse])
async def list_chats(
    agent_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_project_ids = await _get_active_org_project_ids(current_user, db)

    # Own chats: project-less personal chats OR chats in active org's projects
    own_q = select(Chat).where(Chat.user_id == current_user.id, Chat.is_archived == False)  # noqa: E712
    if org_project_ids:
        own_q = own_q.where(or_(Chat.project_id.is_(None), Chat.project_id.in_(org_project_ids)))
    else:
        own_q = own_q.where(Chat.project_id.is_(None))
    own_result = await db.execute(own_q.order_by(desc(Chat.updated_at)))
    own_chats = own_result.scalars().all()

    # Shared chats: other users' chats inside active org's projects
    shared_chats: list[Chat] = []
    if org_project_ids:
        shared_result = await db.execute(
            select(Chat)
            .where(
                Chat.project_id.in_(org_project_ids),
                Chat.user_id != current_user.id,
                Chat.is_archived == False,  # noqa: E712
            )
            .order_by(desc(Chat.updated_at))
        )
        shared_chats = shared_result.scalars().all()

    own_ids = {c.id for c in own_chats}
    all_chats = list(own_chats) + list(shared_chats)

    if agent_id:
        all_chats = [c for c in all_chats if c.agent_id == agent_id]

    creator_ids = {c.user_id for c in all_chats if c.user_id}
    creator_map: dict[str, User] = {}
    if creator_ids:
        r = await db.execute(select(User).where(User.id.in_(creator_ids)))
        for u in r.scalars().all():
            creator_map[u.id] = u

    agent_ids = {c.agent_id for c in all_chats if c.agent_id}
    agent_name_map: dict[str, str] = {}
    if agent_ids:
        r = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        for aid, aname in r.all():
            agent_name_map[aid] = aname

    all_ids = [c.id for c in all_chats]
    subchat_counts: dict[str, int] = {}
    msg_stats: dict[str, dict] = {}

    if all_ids:
        sub_r = await db.execute(
            text(
                "SELECT parent_chat_id, COUNT(*)::int"
                " FROM chats WHERE parent_chat_id = ANY(:ids)"
                " GROUP BY parent_chat_id"
            ),
            {"ids": all_ids},
        )
        subchat_counts = {row[0]: row[1] for row in sub_r.all()}

        stat_r = await db.execute(
            text(
                "SELECT chat_id,"
                " COALESCE(SUM((metadata->'usage'->>'input_tokens')::int), 0)::int,"
                " COALESCE(SUM((metadata->'usage'->>'output_tokens')::int), 0)::int,"
                " COALESCE(SUM((metadata->>'tool_call_count')::int), 0)::int"
                " FROM messages"
                " WHERE chat_id = ANY(:ids) AND metadata IS NOT NULL"
                " GROUP BY chat_id"
            ),
            {"ids": all_ids},
        )
        msg_stats = {
            row[0]: {"input_tokens": row[1], "output_tokens": row[2], "tool_calls": row[3]}
            for row in stat_r.all()
        }

    # Running flag: a chat (or anything in its subtree) has an active task. Lets the
    # sidebar show a spinner on chats with work in flight (incl. autonomous runs).
    running_ids: set[str] = set()
    if all_ids:
        act_r = await db.execute(
            text(
                "SELECT DISTINCT chat_id FROM tasks"
                " WHERE chat_id = ANY(:ids) AND status IN ('pending','queued','in_progress')"
            ),
            {"ids": all_ids},
        )
        running_ids = {row[0] for row in act_r.all() if row[0]}
        # Also: chats with a live turn in progress (set at stream start, short TTL) —
        # so the spinner shows from the first moment, before any task exists.
        try:
            from src.core.stream_buffer import active_chats
            running_ids |= await active_chats(all_ids)
        except Exception:
            pass
        # Propagate up to ancestors within the loaded set so a parent shows active
        # while a descendant sub-chat is working.
        _parent_of = {c.id: c.parent_chat_id for c in all_chats}
        for _cid in list(running_ids):
            _p = _parent_of.get(_cid)
            _seen = set()
            while _p and _p not in _seen:
                _seen.add(_p)
                running_ids.add(_p)
                _p = _parent_of.get(_p)

    result_list = []
    for chat in all_chats:
        creator = creator_map.get(chat.user_id) if chat.user_id else None
        ms = msg_stats.get(chat.id, {})
        result_list.append({
            "id": chat.id,
            "title": chat.title,
            "project_id": chat.project_id,
            "parent_chat_id": chat.parent_chat_id,
            "agent_id": chat.agent_id,
            "agent_name": agent_name_map.get(chat.agent_id, "Deleted agent") if chat.agent_id else None,
            "provider_chain_id": chat.provider_chain_id,
            "direct_provider_id": getattr(chat, "direct_provider_id", None),
            "is_shared": chat.id not in own_ids,
            "created_by_id": chat.user_id,
            "created_by_name": creator.full_name if creator else None,
            "stats": {
                "subchat_count": subchat_counts.get(chat.id, 0),
                "tool_calls": ms.get("tool_calls", 0),
                "input_tokens": ms.get("input_tokens", 0),
                "output_tokens": ms.get("output_tokens", 0),
                "running": chat.id in running_ids,
            },
        })

    return result_list


@router.post("/", response_model=ChatResponse, status_code=201)
async def create_chat(
    req: ChatCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    provider_chain_id = req.provider_chain_id
    agent_id = req.agent_id

    # Resolve effective project list (project_ids takes precedence over project_id)
    effective_project_ids: list[str] = req.project_ids if req.project_ids else ([req.project_id] if req.project_id else [])
    primary_project_id: str | None = effective_project_ids[0] if effective_project_ids else None

    project = None
    if primary_project_id:
        project_result = await db.execute(
            select(Project).where(Project.id == primary_project_id)
        )
        project = project_result.unique().scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if not provider_chain_id:
            provider_chain_id = project.provider_chain_id
        if not agent_id and project.pm_agent_id:
            agent_id = project.pm_agent_id

    chat = Chat(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=req.title,
        project_id=primary_project_id,
        project_ids=effective_project_ids if effective_project_ids else None,
        parent_chat_id=req.parent_chat_id,
        agent_id=agent_id,
        provider_chain_id=provider_chain_id,
        webhook_url=req.webhook_url or None,
        webhook_secret=req.webhook_secret or None,
        sync_response=req.sync_response,
        sync_timeout=max(1, min(30, req.sync_timeout)),
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)

    # Push to the owner's user channel so their sidebar refreshes instantly
    # (no polling). Skip sub-chats — they don't show in the chat list.
    if not chat.parent_chat_id:
        await pubsub.broadcast(f"user:{current_user.id}", {
            "type": "chat_created", "chat_id": chat.id,
        })

    # Broadcast to project/org members so they can refresh their chat lists
    if req.project_id and project:
        await pubsub.broadcast(f"org:{project.org_id}:chats", {
            "type": "chat_created",
            "chat_id": chat.id,
            "project_id": req.project_id,
        })

    return {
        "id": chat.id,
        "title": chat.title,
        "project_id": chat.project_id,
        "parent_chat_id": chat.parent_chat_id,
        "agent_id": chat.agent_id,
        "agent_name": None,
        "provider_chain_id": chat.provider_chain_id,
        "direct_provider_id": getattr(chat, "direct_provider_id", None),
        "is_shared": False,
        "created_by_id": current_user.id,
        "created_by_name": current_user.full_name,
    }


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    agent_name = None
    if chat.agent_id:
        agent_result = await db.execute(select(Agent).where(Agent.id == chat.agent_id))
        agent = agent_result.scalar_one_or_none()
        if agent:
            agent_name = agent.name

    creator = None
    if chat.user_id:
        r = await db.execute(select(User).where(User.id == chat.user_id))
        creator = r.scalar_one_or_none()

    return {
        "id": chat.id,
        "title": chat.title,
        "project_id": chat.project_id,
        "parent_chat_id": chat.parent_chat_id,
        "agent_id": chat.agent_id,
        "agent_name": agent_name,
        "provider_chain_id": chat.provider_chain_id,
        "direct_provider_id": getattr(chat, "direct_provider_id", None),
        "is_shared": chat.user_id != current_user.id,
        "created_by_id": chat.user_id,
        "created_by_name": creator.full_name if creator else None,
        "notes": chat.notes,
        "webhook_url": chat.webhook_url,
        "sync_response": chat.sync_response,
        "sync_timeout": chat.sync_timeout,
    }


@router.get("/{chat_id}/export")
async def export_chat(
    chat_id: str,
    format: str = Query("json", pattern="^(json|markdown)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    msgs_result = await db.scalars(
        select(Message)
        .where(Message.chat_id == chat_id, Message.excluded == False)  # noqa: E712
        .order_by(Message.created_at)
    )
    msgs = list(msgs_result)

    safe_title = (chat.title or "chat").replace("/", "-").replace("\\", "-")[:80]

    if format == "json":
        payload = {
            "id": chat.id,
            "title": chat.title or "Untitled",
            "agent_id": chat.agent_id,
            "created_at": chat.created_at.isoformat(),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "provider_used": m.provider_used,
                    "tokens_used": m.tokens_used,
                    "created_at": m.created_at.isoformat(),
                }
                for m in msgs
                if m.content and m.content.strip()
            ],
        }
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}-{chat_id[:8]}.json"'},
        )

    # format == "markdown"
    lines: list[str] = [f"# {chat.title or 'Untitled Chat'}\n", "*Exported from Nexora*\n\n---\n"]
    for m in msgs:
        if not m.content or not m.content.strip():
            continue
        if m.role == "user":
            role_label = "**User**"
        elif m.role == "assistant":
            role_label = "**Assistant**"
        else:
            role_label = f"**{m.role.capitalize()}**"
        lines.append(f"{role_label}\n\n{m.content}\n\n---\n")
    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}-{chat_id[:8]}.md"'},
    )


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == current_user.id)
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat.is_archived = True
    await db.commit()
    await pubsub.broadcast(f"user:{current_user.id}", {
        "type": "chat_deleted", "chat_id": chat_id,
    })


@router.patch("/{chat_id}/restore", status_code=200)
async def restore_chat(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == current_user.id)
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat.is_archived = False
    await db.commit()
    await pubsub.broadcast(f"user:{current_user.id}", {
        "type": "chat_restored", "chat_id": chat_id,
    })
    return {"id": chat.id, "is_archived": False}


@router.patch("/{chat_id}/provider-chain")
async def update_chat_provider_chain(
    chat_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")
    # Accept either a chain or a direct single provider — mutually exclusive
    if "provider_chain_id" in body:
        chat.provider_chain_id = body["provider_chain_id"]
        chat.direct_provider_id = None
    if "direct_provider_id" in body:
        chat.direct_provider_id = body["direct_provider_id"]
        chat.provider_chain_id = None
    await db.commit()
    return {
        "id": chat.id,
        "provider_chain_id": chat.provider_chain_id,
        "direct_provider_id": chat.direct_provider_id,
    }


@router.patch("/{chat_id}/webhook")
async def update_chat_webhook(
    chat_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")
    if "webhook_url" in body:
        chat.webhook_url = body["webhook_url"] or None
    if "webhook_secret" in body:
        chat.webhook_secret = body["webhook_secret"] or None
    if "sync_response" in body:
        chat.sync_response = bool(body["sync_response"])
    if "sync_timeout" in body:
        timeout = int(body["sync_timeout"])
        chat.sync_timeout = max(1, min(30, timeout))
    await db.commit()
    return {
        "id": chat.id,
        "webhook_url": chat.webhook_url,
        "sync_response": chat.sync_response,
        "sync_timeout": chat.sync_timeout,
    }


async def _resolve_root_chat(chat_id: str, db: AsyncSession) -> Chat:
    r = await db.execute(select(Chat).where(Chat.id == chat_id))
    cur = r.scalar_one_or_none()
    if not cur:
        raise HTTPException(status_code=404, detail="Chat not found")
    visited: set[str] = set()
    while cur and cur.id not in visited:
        visited.add(cur.id)
        if not cur.parent_chat_id:
            break
        r2 = await db.execute(select(Chat).where(Chat.id == cur.parent_chat_id))
        cur = r2.scalar_one_or_none()
    return cur


@router.get("/{chat_id}/notes", response_model=ChatNotesListResponse)
async def get_chat_notes(
    chat_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")
    root = await _resolve_root_chat(chat_id, db)

    total_r = await db.execute(
        select(func.count()).where(ChatNote.chat_id == root.id)
    )
    total = total_r.scalar() or 0

    notes_r = await db.execute(
        select(ChatNote)
        .where(ChatNote.chat_id == root.id)
        .order_by(desc(ChatNote.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    notes = notes_r.scalars().all()
    return {
        "chat_id": root.id,
        "notes": notes,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/{chat_id}/notes", response_model=ChatNoteResponse, status_code=201)
async def create_chat_note(
    chat_id: str,
    body: ChatNoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")
    root = await _resolve_root_chat(chat_id, db)

    note = ChatNote(
        id=str(uuid.uuid4()),
        chat_id=root.id,
        content=body.content,
        description=body.description,
        author=body.author or current_user.full_name,
        source_chat_id=body.source_chat_id,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    await pubsub.broadcast(root.id, {
        "type": "chat_notes_updated",
        "chat_id": root.id,
        "action": "created",
        "note_id": note.id,
    })
    return note


@router.patch("/{chat_id}/notes/{note_id}", response_model=ChatNoteResponse)
async def update_chat_note(
    chat_id: str,
    note_id: str,
    body: ChatNoteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")
    root = await _resolve_root_chat(chat_id, db)

    note_r = await db.execute(
        select(ChatNote).where(ChatNote.id == note_id, ChatNote.chat_id == root.id)
    )
    note = note_r.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if body.content is not None:
        note.content = body.content
    if body.description is not None:
        note.description = body.description
    if body.author is not None:
        note.author = body.author
    await db.commit()
    await db.refresh(note)

    await pubsub.broadcast(root.id, {
        "type": "chat_notes_updated",
        "chat_id": root.id,
        "action": "updated",
        "note_id": note.id,
    })
    return note


@router.delete("/{chat_id}/notes/{note_id}", status_code=204)
async def delete_chat_note(
    chat_id: str,
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")
    root = await _resolve_root_chat(chat_id, db)

    note_r = await db.execute(
        select(ChatNote).where(ChatNote.id == note_id, ChatNote.chat_id == root.id)
    )
    note = note_r.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    await db.delete(note)
    await db.commit()

    await pubsub.broadcast(root.id, {
        "type": "chat_notes_updated",
        "chat_id": root.id,
        "action": "deleted",
        "note_id": note_id,
    })


@router.patch("/{chat_id}/title")
async def update_chat_title(
    chat_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")
    new_title = body.get("title", chat.title)
    if not isinstance(new_title, str) or not new_title.strip():
        raise HTTPException(status_code=422, detail="Title must be a non-empty string")
    chat.title = new_title[:256]
    await db.commit()
    return {"id": chat.id, "title": chat.title}
