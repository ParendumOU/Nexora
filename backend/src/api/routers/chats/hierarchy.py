import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.database import get_db
from src.api.deps import get_current_user
from src.models.user import User
from src.models.chat import Chat, Message
from src.models.agent import Agent
from src.api.routers.chats.access import _can_access_chat
from src.api.routers.chats.schemas import ForkRequest

router = APIRouter()


@router.post("/{chat_id}/fork", status_code=201)
async def fork_chat(
    chat_id: str,
    req: ForkRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    ref_result = await db.execute(
        select(Message).where(Message.id == req.before_message_id, Message.chat_id == chat_id)
    )
    ref_msg = ref_result.scalar_one_or_none()
    if not ref_msg:
        raise HTTPException(status_code=404, detail="Message not found")

    prior_result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id, Message.created_at < ref_msg.created_at)
        .order_by(Message.created_at)
    )
    prior_messages = prior_result.scalars().all()

    new_chat = Chat(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=chat.title,
        project_id=chat.project_id,
        parent_chat_id=None,
        agent_id=chat.agent_id,
        provider_chain_id=chat.provider_chain_id,
    )
    db.add(new_chat)
    await db.flush()

    for msg in prior_messages:
        db.add(Message(
            id=str(uuid.uuid4()),
            chat_id=new_chat.id,
            role=msg.role,
            content=msg.content,
            metadata_=msg.metadata_,
            provider_used=msg.provider_used,
            agent_id=msg.agent_id,
            user_id=msg.user_id,
            created_at=msg.created_at,
        ))

    await db.commit()
    return {"new_chat_id": new_chat.id}


@router.get("/{chat_id}/hierarchy")
async def get_chat_hierarchy(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    from src.models.task import Task

    start_r = await db.execute(select(Chat).where(Chat.id == chat_id))
    start_chat = start_r.scalar_one_or_none()
    if not start_chat or not await _can_access_chat(current_user.id, start_chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    # ── Collect ancestor chain (root-first) ──────────────────────────────────
    ancestor_chain: list[Chat] = []
    cur = start_chat
    visited_up: set[str] = {start_chat.id}
    while cur.parent_chat_id and cur.parent_chat_id not in visited_up:
        parent_r = await db.execute(select(Chat).where(Chat.id == cur.parent_chat_id))
        parent = parent_r.scalar_one_or_none()
        if not parent or not await _can_access_chat(current_user.id, parent, db):
            break
        visited_up.add(parent.id)
        ancestor_chain.append(parent)
        cur = parent
    ancestor_chain.reverse()  # now: [root, ..., direct_parent]
    true_root_id = ancestor_chain[0].id if ancestor_chain else start_chat.id

    # ── BFS down from start_chat ─────────────────────────────────────────────
    queue: list[tuple[Chat, int]] = [(start_chat, 0)]
    bfs_seen: set[str] = set()
    descendant_chats: list[tuple[Chat, int]] = []
    while queue:
        current, depth = queue.pop(0)
        if current.id in bfs_seen:
            continue
        bfs_seen.add(current.id)
        descendant_chats.append((current, depth))
        children_r = await db.execute(
            select(Chat).where(Chat.parent_chat_id == current.id)
        )
        for child in children_r.scalars().all():
            if child.id not in bfs_seen:
                queue.append((child, depth + 1))

    # Ancestors get negative depths so they sit above start_chat (depth=0)
    n_anc = len(ancestor_chain)
    ancestor_with_depth: list[tuple[Chat, int]] = [
        (chat, -(n_anc - i)) for i, chat in enumerate(ancestor_chain)
    ]
    all_chats_depth = ancestor_with_depth + descendant_chats
    all_chat_ids = [c.id for c, _ in all_chats_depth]
    all_seen_ids = {c.id for c, _ in all_chats_depth}

    # ── Batch: task counts ───────────────────────────────────────────────────
    counts_r = await db.execute(
        select(Task.chat_id, Task.status, func.count(Task.id))
        .where(Task.chat_id.in_(all_chat_ids))
        .group_by(Task.chat_id, Task.status)
    )
    counts_map: dict[str, dict[str, int]] = {}
    for cid, status, cnt in counts_r.all():
        counts_map.setdefault(cid, {})[status] = cnt

    # ── Batch: message counts (detect conversational completions) ────────────
    from sqlalchemy import func as _func
    msg_r = await db.execute(
        select(Message.chat_id, _func.count(Message.id))
        .where(Message.chat_id.in_(all_chat_ids), Message.role == "assistant")
        .group_by(Message.chat_id)
    )
    msg_counts: dict[str, int] = dict(msg_r.all())

    # ── Agent names ──────────────────────────────────────────────────────────
    agent_ids = {c.agent_id for c, _ in all_chats_depth if c.agent_id}
    agent_map: dict[str, str] = {}
    for aid in agent_ids:
        r = await db.execute(select(Agent).where(Agent.id == aid))
        a = r.scalar_one_or_none()
        if a:
            agent_map[aid] = a.name

    def _compute_status(chat: Chat) -> str:
        counts = counts_map.get(chat.id, {})
        running   = counts.get("in_progress", 0)
        failed    = counts.get("failed", 0)
        completed = counts.get("completed", 0)
        pending   = counts.get("pending", 0)
        queued    = counts.get("queued", 0)
        total     = sum(counts.values())
        if running > 0:
            return "running"
        if failed > 0:
            return "failed"
        if queued + pending > 0:
            return "stalled"
        if total > 0 and completed == total:
            return "completed"
        if total == 0 and msg_counts.get(chat.id, 0) > 0:
            return "completed"
        return "idle"

    def _task_counts(chat: Chat) -> dict:
        counts = counts_map.get(chat.id, {})
        return {
            "total":     sum(counts.values()),
            "running":   counts.get("in_progress", 0),
            "failed":    counts.get("failed", 0),
            "completed": counts.get("completed", 0),
            "pending":   counts.get("pending", 0),
            "queued":    counts.get("queued", 0),
            "paused":    counts.get("paused", 0),
        }

    nodes = []
    edges = []

    for chat, depth in all_chats_depth:
        if depth < 0:
            node_type = "ancestor"
        elif depth == 0:
            node_type = "current"
        else:
            node_type = "descendant"

        nodes.append({
            "id":             chat.id,
            "title":          chat.title,
            "agent_name":     agent_map.get(chat.agent_id) if chat.agent_id else None,
            "parent_chat_id": chat.parent_chat_id,
            "depth":          depth,
            "node_type":      node_type,
            "task_counts":    _task_counts(chat),
            "status":         _compute_status(chat),
        })

    # Ancestor-chain edges
    for i in range(len(ancestor_chain) - 1):
        edges.append({"source": ancestor_chain[i].id, "target": ancestor_chain[i + 1].id})
    if ancestor_chain:
        edges.append({"source": ancestor_chain[-1].id, "target": start_chat.id})

    # Descendant edges (skip start_chat itself)
    for chat, _ in descendant_chats[1:]:
        if chat.parent_chat_id and chat.parent_chat_id in all_seen_ids:
            edges.append({"source": chat.parent_chat_id, "target": chat.id})

    return {"root_id": true_root_id, "anchor_id": start_chat.id, "nodes": nodes, "edges": edges}
