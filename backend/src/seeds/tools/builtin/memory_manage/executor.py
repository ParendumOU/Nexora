import logging
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.agent import Agent
from src.models.agent_memory import AgentMemory, MEMORY_TYPES as AGENT_MEMORY_TYPES
from src.models.project_memory import ProjectMemory, MEMORY_TYPES as PROJECT_MEMORY_TYPES
from src.models.thread_memory import ThreadMemory, MEMORY_TYPES as THREAD_MEMORY_TYPES

logger = logging.getLogger(__name__)

_VALID_SCOPES = {"agent", "project", "thread"}
_VALID_ACTIONS = {"save", "read", "delete"}


async def _resolve_org_id(db, agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    ra = await db.execute(select(Agent).where(Agent.id == agent_id))
    ag = ra.scalar_one_or_none()
    return ag.org_id if ag else None


async def _resolve_root_chat_id(db, chat_id: str) -> str:
    """Walk up parent_chat_id chain to find the root chat of this thread."""
    current_id = chat_id
    visited: set[str] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        rc = await db.execute(select(Chat.id, Chat.parent_chat_id).where(Chat.id == current_id))
        row = rc.one_or_none()
        if not row or not row[1]:
            return current_id
        current_id = row[1]
    return chat_id  # fallback


async def _save(args: dict, chat_id: str, agent_id: str | None) -> dict:
    content = (args.get("content") or "").strip()
    if not content:
        return {"error": "content is required"}

    scope = (args.get("scope") or "agent").lower()
    if scope not in _VALID_SCOPES:
        return {"error": f"scope must be one of: {', '.join(_VALID_SCOPES)}"}

    mem_type = (args.get("type") or "fact").lower()
    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    priority = max(1, min(5, int(args.get("priority") or 3)))

    async with AsyncSessionLocal() as db:
        rc = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = rc.scalar_one_or_none()
        if not chat:
            return {"error": "Chat not found"}

        org_id = await _resolve_org_id(db, agent_id)

        if scope == "project":
            if mem_type not in PROJECT_MEMORY_TYPES:
                mem_type = "fact"

            project_id = chat.project_id
            if not project_id:
                return {"error": "This chat is not linked to a project. Use scope='agent' instead."}

            if not org_id:
                from src.models.project import Project
                rp = await db.execute(select(Project).where(Project.id == project_id))
                proj = rp.unique().scalar_one_or_none()
                if proj:
                    org_id = proj.org_id

            if not org_id:
                return {"error": "Could not resolve org_id for this project"}

            mem = ProjectMemory(
                id=str(uuid.uuid4()),
                project_id=project_id,
                org_id=org_id,
                agent_id=agent_id,
                type=mem_type,
                content=content,
                tags=tags,
                priority=priority,
            )
            db.add(mem)
            await db.commit()
            await db.refresh(mem)
            logger.info(f"[memory_manage] project memory {mem.id} saved for project {project_id}")
            return {"data": {"id": mem.id, "scope": "project", "type": mem.type, "content": mem.content}}

        else:
            if mem_type not in AGENT_MEMORY_TYPES:
                mem_type = "fact"

            if not agent_id:
                return {"error": "agent_id is required for agent-scoped memory"}
            if not org_id:
                return {"error": "Could not resolve org_id for this agent"}

            mem = AgentMemory(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                org_id=org_id,
                type=mem_type,
                content=content,
                tags=tags,
                priority=priority,
            )
            db.add(mem)
            await db.commit()
            await db.refresh(mem)
            logger.info(f"[memory_manage] agent memory {mem.id} saved for agent {agent_id}")
            return {"data": {"id": mem.id, "scope": "agent", "type": mem.type, "content": mem.content}}


async def _read(args: dict, chat_id: str, agent_id: str | None) -> dict:
    scope = (args.get("scope") or "agent").lower()
    if scope not in _VALID_SCOPES:
        return {"error": f"scope must be one of: {', '.join(_VALID_SCOPES)}"}

    mem_type = (args.get("type") or "").lower() or None
    search = (args.get("search") or "").strip() or None
    tags_filter = args.get("tags") or []
    if isinstance(tags_filter, str):
        tags_filter = [t.strip() for t in tags_filter.split(",") if t.strip()]
    limit = min(int(args.get("limit") or 20), 50)

    async with AsyncSessionLocal() as db:
        if scope == "project":
            rc = await db.execute(select(Chat).where(Chat.id == chat_id))
            chat = rc.scalar_one_or_none()
            project_id = chat.project_id if chat else None
            if not project_id:
                return {"error": "This chat is not linked to a project. Use scope='agent' instead."}
            q = select(ProjectMemory).where(ProjectMemory.project_id == project_id)
            if mem_type:
                q = q.where(ProjectMemory.type == mem_type)
            q = q.order_by(ProjectMemory.priority.desc(), ProjectMemory.created_at).limit(limit * 3)
            r = await db.execute(q)
            raw = r.scalars().all()
        else:
            if not agent_id:
                return {"error": "agent_id is required for agent-scoped memory"}
            q = select(AgentMemory).where(AgentMemory.agent_id == agent_id)
            if mem_type:
                q = q.where(AgentMemory.type == mem_type)
            q = q.order_by(AgentMemory.priority.desc(), AgentMemory.created_at).limit(limit * 3)
            r = await db.execute(q)
            raw = r.scalars().all()

    results = []
    for m in raw:
        if tags_filter:
            m_tags = m.tags or []
            if not any(t in m_tags for t in tags_filter):
                continue
        if search and search.lower() not in m.content.lower():
            continue
        results.append({
            "id": m.id,
            "type": m.type,
            "tags": m.tags or [],
            "content": m.content,
            "priority": m.priority,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
        if len(results) >= limit:
            break

    logger.debug(f"[memory_manage] {len(results)} memories returned for agent={agent_id} scope={scope}")
    return {"data": {"memories": results, "count": len(results), "scope": scope}}


async def _delete(args: dict, agent_id: str | None) -> dict:
    memory_id = (args.get("memory_id") or "").strip()
    if not memory_id:
        return {"error": "memory_id is required"}

    scope = (args.get("scope") or "agent").lower()

    async with AsyncSessionLocal() as db:
        org_id = await _resolve_org_id(db, agent_id)

        if scope == "project":
            r = await db.execute(select(ProjectMemory).where(ProjectMemory.id == memory_id))
            mem = r.scalar_one_or_none()
            if not mem:
                return {"error": f"Project memory '{memory_id}' not found"}
            if org_id and mem.org_id != org_id:
                return {"error": "Permission denied"}
            await db.delete(mem)
            await db.commit()
            logger.info(f"[memory_manage] project memory {memory_id} deleted")
        else:
            r = await db.execute(select(AgentMemory).where(AgentMemory.id == memory_id))
            mem = r.scalar_one_or_none()
            if not mem:
                return {"error": f"Agent memory '{memory_id}' not found"}
            if org_id and mem.org_id != org_id:
                return {"error": "Permission denied"}
            await db.delete(mem)
            await db.commit()
            logger.info(f"[memory_manage] agent memory {memory_id} deleted")

    return {"data": {"deleted": memory_id, "scope": scope}}


async def _save_thread(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    content = (args.get("content") or "").strip()
    if not content:
        return {"error": "content is required"}

    mem_type = (args.get("type") or "fact").lower()
    if mem_type not in THREAD_MEMORY_TYPES:
        mem_type = "fact"

    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    priority = max(1, min(5, int(args.get("priority") or 3)))
    key = (args.get("key") or "").strip() or None
    data = args.get("data") or None

    async with AsyncSessionLocal() as db:
        root_chat_id = await _resolve_root_chat_id(db, chat_id)
        mem = ThreadMemory(
            id=str(uuid.uuid4()),
            root_chat_id=root_chat_id,
            chat_id=chat_id,
            agent_id=agent_id,
            agent_name=agent_name,
            key=key,
            type=mem_type,
            content=content,
            data=data,
            tags=tags,
            priority=priority,
        )
        db.add(mem)
        await db.commit()
        await db.refresh(mem)
        logger.info(f"[memory_manage] thread memory {mem.id} saved for thread {root_chat_id} by {agent_name}")
    return {"data": {"id": mem.id, "scope": "thread", "root_chat_id": root_chat_id, "key": key, "type": mem.type, "content": mem.content}}


async def _read_thread(args: dict, chat_id: str) -> dict:
    mem_type = (args.get("type") or "").lower() or None
    search = (args.get("search") or "").strip() or None
    key_filter = (args.get("key") or "").strip() or None
    tags_filter = args.get("tags") or []
    if isinstance(tags_filter, str):
        tags_filter = [t.strip() for t in tags_filter.split(",") if t.strip()]
    limit = min(int(args.get("limit") or 50), 100)

    async with AsyncSessionLocal() as db:
        root_chat_id = await _resolve_root_chat_id(db, chat_id)
        q = select(ThreadMemory).where(ThreadMemory.root_chat_id == root_chat_id)
        if mem_type:
            q = q.where(ThreadMemory.type == mem_type)
        if key_filter:
            q = q.where(ThreadMemory.key == key_filter)
        q = q.order_by(ThreadMemory.priority.desc(), ThreadMemory.created_at)
        r = await db.execute(q)
        raw = r.scalars().all()

    results = []
    for m in raw:
        if tags_filter:
            m_tags = m.tags or []
            if not any(t in m_tags for t in tags_filter):
                continue
        if search and search.lower() not in m.content.lower():
            continue
        entry: dict = {
            "id": m.id,
            "key": m.key,
            "type": m.type,
            "tags": m.tags or [],
            "content": m.content,
            "priority": m.priority,
            "agent_name": m.agent_name,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        if m.data is not None:
            entry["data"] = m.data
        results.append(entry)
        if len(results) >= limit:
            break

    logger.debug(f"[memory_manage] {len(results)} thread memories returned for root={root_chat_id}")
    return {"data": {"memories": results, "count": len(results), "scope": "thread", "root_chat_id": root_chat_id}}


async def _delete_thread(args: dict, chat_id: str) -> dict:
    memory_id = (args.get("memory_id") or "").strip()
    if not memory_id:
        return {"error": "memory_id is required"}

    async with AsyncSessionLocal() as db:
        root_chat_id = await _resolve_root_chat_id(db, chat_id)
        r = await db.execute(select(ThreadMemory).where(ThreadMemory.id == memory_id, ThreadMemory.root_chat_id == root_chat_id))
        mem = r.scalar_one_or_none()
        if not mem:
            return {"error": f"Thread memory '{memory_id}' not found in this thread"}
        await db.delete(mem)
        await db.commit()
        logger.info(f"[memory_manage] thread memory {memory_id} deleted from thread {root_chat_id}")
    return {"data": {"deleted": memory_id, "scope": "thread"}}


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    # Resolve agent_id from chat record if not provided by caller
    if not agent_id:
        async with AsyncSessionLocal() as db:
            rc = await db.execute(select(Chat).where(Chat.id == chat_id))
            chat = rc.scalar_one_or_none()
            if chat and chat.agent_id:
                agent_id = chat.agent_id

    action = (args.get("action") or "").strip().lower()
    if not action:
        return {"error": "action is required (save | read | delete)"}
    if action not in _VALID_ACTIONS:
        return {"error": f"action must be one of: {', '.join(_VALID_ACTIONS)}"}

    scope = (args.get("scope") or "agent").lower()

    if scope == "thread":
        if action == "save":
            return await _save_thread(args, chat_id, agent_id, agent_name)
        elif action == "read":
            return await _read_thread(args, chat_id)
        else:
            return await _delete_thread(args, chat_id)

    if action == "save":
        return await _save(args, chat_id, agent_id)
    elif action == "read":
        return await _read(args, chat_id, agent_id)
    else:
        return await _delete(args, agent_id)
