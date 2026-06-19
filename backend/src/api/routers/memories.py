"""Memory management API — agent-scoped and project-scoped persistent memories."""
import asyncio
import uuid
import logging
from typing import Literal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.agent_memory import AgentMemory
from src.models.project_memory import ProjectMemory
from src.models.agent import Agent
from src.models.project import Project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/memories", tags=["memories"])

MemoryScope = Literal["agent", "project"]
MemoryType = Literal["fact", "decision", "context", "instruction"]


class MemoryOut(BaseModel):
    id: str
    scope: MemoryScope
    type: str
    content: str
    tags: list
    priority: int
    agent_id: str | None
    project_id: str | None
    org_id: str
    created_at: datetime
    updated_at: datetime


class MemoryCreate(BaseModel):
    scope: MemoryScope = "agent"
    type: MemoryType = "fact"
    content: str = Field(..., min_length=1)
    tags: list[str] = []
    priority: int = Field(default=3, ge=1, le=5)
    agent_id: str | None = None
    project_id: str | None = None


class MemoryUpdate(BaseModel):
    type: MemoryType | None = None
    content: str | None = None
    tags: list[str] | None = None
    priority: int | None = Field(default=None, ge=1, le=5)


def _agent_mem_to_out(m: AgentMemory) -> MemoryOut:
    return MemoryOut(
        id=m.id, scope="agent", type=m.type, content=m.content,
        tags=m.tags or [], priority=m.priority,
        agent_id=m.agent_id, project_id=None, org_id=m.org_id,
        created_at=m.created_at, updated_at=m.updated_at,
    )


def _project_mem_to_out(m: ProjectMemory) -> MemoryOut:
    return MemoryOut(
        id=m.id, scope="project", type=m.type, content=m.content,
        tags=m.tags or [], priority=m.priority,
        agent_id=m.agent_id, project_id=m.project_id, org_id=m.org_id,
        created_at=m.created_at, updated_at=m.updated_at,
    )


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    scope: MemoryScope | None = Query(None),
    agent_id: str | None = Query(None),
    project_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    results: list[MemoryOut] = []

    if scope in (None, "agent"):
        q = select(AgentMemory).where(AgentMemory.org_id == org_id)
        if agent_id:
            q = q.where(AgentMemory.agent_id == agent_id)
        q = q.order_by(AgentMemory.priority.desc(), AgentMemory.created_at)
        r = await db.execute(q)
        results += [_agent_mem_to_out(m) for m in r.scalars().all()]

    if scope in (None, "project"):
        q = select(ProjectMemory).where(ProjectMemory.org_id == org_id)
        if project_id:
            q = q.where(ProjectMemory.project_id == project_id)
        if agent_id:
            q = q.where(ProjectMemory.agent_id == agent_id)
        q = q.order_by(ProjectMemory.priority.desc(), ProjectMemory.created_at)
        r = await db.execute(q)
        results += [_project_mem_to_out(m) for m in r.scalars().all()]

    return results


@router.post("", response_model=MemoryOut, status_code=201)
async def create_memory(
    body: MemoryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)

    if body.scope == "agent":
        if not body.agent_id:
            raise HTTPException(400, "agent_id is required for agent-scoped memory")
        r = await db.execute(select(Agent).where(Agent.id == body.agent_id, Agent.org_id == org_id))
        if not r.scalar_one_or_none():
            raise HTTPException(404, "Agent not found")
        from src.services.embeddings import embed as _embed
        embedding = await _embed(body.content, org_id)
        mem = AgentMemory(
            id=str(uuid.uuid4()), agent_id=body.agent_id, org_id=org_id,
            type=body.type, content=body.content, tags=body.tags, priority=body.priority,
            embedding=embedding,
        )
        db.add(mem)
        await db.commit()
        await db.refresh(mem)
        return _agent_mem_to_out(mem)
    else:
        if not body.project_id:
            raise HTTPException(400, "project_id is required for project-scoped memory")
        r = await db.execute(select(Project).where(Project.id == body.project_id, Project.org_id == org_id))
        if not r.unique().scalar_one_or_none():
            raise HTTPException(404, "Project not found")
        from src.services.embeddings import embed as _embed
        embedding = await _embed(body.content, org_id)
        mem = ProjectMemory(
            id=str(uuid.uuid4()), project_id=body.project_id, org_id=org_id,
            agent_id=body.agent_id, type=body.type, content=body.content,
            tags=body.tags, priority=body.priority, embedding=embedding,
        )
        db.add(mem)
        await db.commit()
        await db.refresh(mem)
        return _project_mem_to_out(mem)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    scope: MemoryScope = Query("agent"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)

    if scope == "agent":
        r = await db.execute(select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.org_id == org_id))
        mem = r.scalar_one_or_none()
        if not mem:
            raise HTTPException(404, "Memory not found")
        if body.type is not None:
            mem.type = body.type
        if body.content is not None:
            mem.content = body.content
            from src.services.embeddings import embed as _embed
            mem.embedding = await _embed(body.content, org_id)
        if body.tags is not None:
            mem.tags = body.tags
        if body.priority is not None:
            mem.priority = body.priority
        await db.commit()
        await db.refresh(mem)
        return _agent_mem_to_out(mem)
    else:
        r = await db.execute(select(ProjectMemory).where(ProjectMemory.id == memory_id, ProjectMemory.org_id == org_id))
        mem = r.scalar_one_or_none()
        if not mem:
            raise HTTPException(404, "Memory not found")
        if body.type is not None:
            mem.type = body.type
        if body.content is not None:
            mem.content = body.content
            from src.services.embeddings import embed as _embed
            mem.embedding = await _embed(body.content, org_id)
        if body.tags is not None:
            mem.tags = body.tags
        if body.priority is not None:
            mem.priority = body.priority
        await db.commit()
        await db.refresh(mem)
        return _project_mem_to_out(mem)


class MemorySearchResult(BaseModel):
    id: str
    scope: MemoryScope
    type: str
    content: str
    tags: list
    priority: int
    agent_id: str | None
    project_id: str | None
    org_id: str
    score: float
    created_at: datetime
    updated_at: datetime


@router.get("/search", response_model=list[MemorySearchResult])
async def search_memories(
    q: str = Query(..., min_length=1),
    scope: MemoryScope | None = Query(None),
    agent_id: str | None = Query(None),
    project_id: str | None = Query(None),
    top_k: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    from src.services.embeddings import embed as _embed, semantic_search, _keyword_score, _cosine

    query_vec = await _embed(q, org_id)

    candidates: list = []
    if scope in (None, "agent"):
        qb = select(AgentMemory).where(AgentMemory.org_id == org_id)
        if agent_id:
            qb = qb.where(AgentMemory.agent_id == agent_id)
        r = await db.execute(qb)
        candidates += [("agent", m) for m in r.scalars().all()]

    if scope in (None, "project"):
        qb = select(ProjectMemory).where(ProjectMemory.org_id == org_id)
        if project_id:
            qb = qb.where(ProjectMemory.project_id == project_id)
        if agent_id:
            qb = qb.where(ProjectMemory.agent_id == agent_id)
        r = await db.execute(qb)
        candidates += [("project", m) for m in r.scalars().all()]

    scored = []
    for mem_scope, mem in candidates:
        emb = getattr(mem, "embedding", None)
        if query_vec and emb and len(emb) == len(query_vec):
            score = _cosine(query_vec, emb)
        else:
            score = _keyword_score(q, mem.content)
        scored.append((score, mem_scope, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, mem_scope, mem in scored[:top_k]:
        if mem_scope == "agent":
            base = _agent_mem_to_out(mem)
        else:
            base = _project_mem_to_out(mem)
        results.append(MemorySearchResult(
            **{**base.model_dump(), "scope": mem_scope, "score": round(score, 4)}
        ))
    return results


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: str,
    scope: MemoryScope = Query("agent"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)

    if scope == "agent":
        r = await db.execute(select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.org_id == org_id))
        mem = r.scalar_one_or_none()
        if not mem:
            raise HTTPException(404, "Memory not found")
        await db.delete(mem)
    else:
        r = await db.execute(select(ProjectMemory).where(ProjectMemory.id == memory_id, ProjectMemory.org_id == org_id))
        mem = r.scalar_one_or_none()
        if not mem:
            raise HTTPException(404, "Memory not found")
        await db.delete(mem)
    await db.commit()
