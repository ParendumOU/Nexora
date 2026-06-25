"""Knowledge base API — create, ingest files, ingest URLs, search, delete."""
import asyncio
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.core.permissions import require_org_role
from src.models.org import OrgRole
from src.models.user import User
from src.models.knowledge_base import KnowledgeBase, KnowledgeFile, KnowledgeChunk

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])

_MAX_FILE_MB = 50
_ALLOWED_TYPES = {
    "application/pdf", "text/plain", "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/x-python", "application/json", "text/csv",
    "application/octet-stream",  # allow generic — extension check below
}
_ALLOWED_EXT = {
    ".pdf", ".txt", ".md", ".docx", ".py", ".ts", ".tsx", ".js", ".jsx",
    ".json", ".yaml", ".yml", ".csv", ".rst", ".html", ".go", ".rs", ".rb",
}


_VALID_STRATEGIES = {"fixed", "sentence", "paragraph"}


class KBCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    project_id: str | None = None
    chunk_strategy: str = Field(default="fixed")
    chunk_size: int = Field(default=512, ge=64, le=2048)
    chunk_overlap: int = Field(default=50, ge=0)

    def model_post_init(self, __context: object) -> None:
        if self.chunk_strategy not in _VALID_STRATEGIES:
            raise ValueError(f"chunk_strategy must be one of: {', '.join(sorted(_VALID_STRATEGIES))}")
        max_overlap = self.chunk_size // 2
        if self.chunk_overlap > max_overlap:
            raise ValueError(f"chunk_overlap must be <= chunk_size / 2 ({max_overlap})")


class KBUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    chunk_strategy: str | None = None
    chunk_size: int | None = Field(default=None, ge=64, le=2048)
    chunk_overlap: int | None = Field(default=None, ge=0)

    def model_post_init(self, __context: object) -> None:
        if self.chunk_strategy is not None and self.chunk_strategy not in _VALID_STRATEGIES:
            raise ValueError(f"chunk_strategy must be one of: {', '.join(sorted(_VALID_STRATEGIES))}")


class KBResponse(BaseModel):
    id: str
    org_id: str
    project_id: str | None
    name: str
    description: str | None
    chunk_strategy: str
    chunk_size: int
    chunk_overlap: int
    file_count: int = 0


class KBFileResponse(BaseModel):
    id: str
    kb_id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    chunk_count: int
    error: str | None
    source_url: str | None = None


class URLIngestRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)


class URLIngestResponse(BaseModel):
    ok: bool
    file_id: str
    title: str
    chars: int


class ChunkResult(BaseModel):
    chunk_id: str
    file_id: str
    filename: str
    content: str
    score: float
    chunk_index: int


# ── KB CRUD ────────────────────────────────────────────────────────────────────

@router.post("", response_model=KBResponse, status_code=201)
async def create_kb(
    body: KBCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    kb = KnowledgeBase(
        id=str(uuid.uuid4()), org_id=org_id,
        project_id=body.project_id, name=body.name, description=body.description,
        chunk_strategy=body.chunk_strategy,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
    )
    db.add(kb)
    await db.commit()
    return KBResponse(id=kb.id, org_id=org_id, project_id=kb.project_id,
                      name=kb.name, description=kb.description,
                      chunk_strategy=kb.chunk_strategy,
                      chunk_size=kb.chunk_size,
                      chunk_overlap=kb.chunk_overlap)


@router.get("", response_model=list[KBResponse])
async def list_kbs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.org_id == org_id))
    kbs = r.scalars().all()
    if not kbs:
        return []
    # #193: one grouped count instead of a COUNT query per KB.
    kb_ids = [kb.id for kb in kbs]
    fc_r = await db.execute(
        select(KnowledgeFile.kb_id, func.count())
        .where(KnowledgeFile.kb_id.in_(kb_ids))
        .group_by(KnowledgeFile.kb_id)
    )
    counts = {row[0]: row[1] for row in fc_r.all()}
    results = []
    for kb in kbs:
        results.append(KBResponse(
            id=kb.id, org_id=org_id, project_id=kb.project_id,
            name=kb.name, description=kb.description,
            chunk_strategy=kb.chunk_strategy,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
            file_count=counts.get(kb.id, 0),
        ))
    return results


@router.get("/{kb_id}", response_model=KBResponse)
async def get_kb(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == org_id))
    kb = r.scalar_one_or_none()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    fc = await db.execute(select(KnowledgeFile).where(KnowledgeFile.kb_id == kb_id))
    return KBResponse(id=kb.id, org_id=org_id, project_id=kb.project_id,
                      name=kb.name, description=kb.description,
                      chunk_strategy=kb.chunk_strategy,
                      chunk_size=kb.chunk_size,
                      chunk_overlap=kb.chunk_overlap,
                      file_count=len(fc.scalars().all()))


@router.patch("/{kb_id}", response_model=KBResponse)
async def update_kb(
    kb_id: str,
    body: KBUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update knowledge base metadata and/or chunking configuration."""
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == org_id))
    kb = r.scalar_one_or_none()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")

    # Validate overlap against effective chunk_size
    effective_size = body.chunk_size if body.chunk_size is not None else kb.chunk_size
    if body.chunk_overlap is not None and body.chunk_overlap > effective_size // 2:
        raise HTTPException(400, f"chunk_overlap must be <= chunk_size / 2 ({effective_size // 2})")

    if body.name is not None:
        kb.name = body.name
    if body.description is not None:
        kb.description = body.description
    if body.chunk_strategy is not None:
        kb.chunk_strategy = body.chunk_strategy
    if body.chunk_size is not None:
        kb.chunk_size = body.chunk_size
    if body.chunk_overlap is not None:
        kb.chunk_overlap = body.chunk_overlap

    await db.commit()
    await db.refresh(kb)

    fc = await db.execute(select(KnowledgeFile).where(KnowledgeFile.kb_id == kb_id))
    return KBResponse(id=kb.id, org_id=org_id, project_id=kb.project_id,
                      name=kb.name, description=kb.description,
                      chunk_strategy=kb.chunk_strategy,
                      chunk_size=kb.chunk_size,
                      chunk_overlap=kb.chunk_overlap,
                      file_count=len(fc.scalars().all()))


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == org_id))
    kb = r.scalar_one_or_none()
    if not kb:
        raise HTTPException(404, "Knowledge base not found")
    await db.delete(kb)
    await db.commit()


# ── File upload ────────────────────────────────────────────────────────────────

@router.post("/{kb_id}/files", response_model=KBFileResponse, status_code=201)
async def upload_file(
    kb_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from pathlib import Path as _Path
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == org_id))
    if not r.scalar_one_or_none():
        raise HTTPException(404, "Knowledge base not found")

    ext = _Path(file.filename or "").suffix.lower()
    ct = file.content_type or "application/octet-stream"
    if ext not in _ALLOWED_EXT and ct not in _ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {ext or ct}")

    data = await file.read()
    if len(data) > _MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(400, f"File exceeds {_MAX_FILE_MB} MB limit")

    kf = KnowledgeFile(
        id=str(uuid.uuid4()), kb_id=kb_id, org_id=org_id,
        filename=file.filename or "upload",
        content_type=ct, size_bytes=len(data), status="pending",
    )
    db.add(kf)
    await db.commit()
    await db.refresh(kf)

    # Background ingest
    from src.services.knowledge_ingest import ingest_file
    asyncio.create_task(ingest_file(kf.id, org_id, kb_id, data, ct, kf.filename))

    return KBFileResponse(
        id=kf.id, kb_id=kb_id, filename=kf.filename, content_type=ct,
        size_bytes=len(data), status="pending", chunk_count=0, error=None,
    )


@router.get("/{kb_id}/files", response_model=list[KBFileResponse])
async def list_files(
    kb_id: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == org_id))
    if not r.scalar_one_or_none():
        raise HTTPException(404, "Knowledge base not found")
    # #194: paginate — a KB can hold thousands of files.
    fr = await db.execute(
        select(KnowledgeFile).where(KnowledgeFile.kb_id == kb_id)
        .order_by(KnowledgeFile.created_at.desc()).limit(limit).offset(offset)
    )
    return [KBFileResponse(
        id=f.id, kb_id=kb_id, filename=f.filename, content_type=f.content_type,
        size_bytes=f.size_bytes, status=f.status, chunk_count=f.chunk_count, error=f.error,
        source_url=f.source_url,
    ) for f in fr.scalars().all()]


@router.delete("/{kb_id}/files/{file_id}", status_code=204)
async def delete_file(
    kb_id: str, file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    r = await db.execute(select(KnowledgeFile).where(
        KnowledgeFile.id == file_id, KnowledgeFile.kb_id == kb_id, KnowledgeFile.org_id == org_id
    ))
    kf = r.scalar_one_or_none()
    if not kf:
        raise HTTPException(404, "File not found")
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.file_id == file_id))
    await db.delete(kf)
    await db.commit()


# ── URL ingestion ──────────────────────────────────────────────────────────────

@router.post("/{kb_id}/ingest-url", response_model=URLIngestResponse, status_code=201)
async def ingest_url(
    kb_id: str,
    body: URLIngestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a web URL, extract text, chunk and embed it into the knowledge base."""
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http:// or https://")

    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.member, db)
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == org_id))
    if not r.scalar_one_or_none():
        raise HTTPException(404, "Knowledge base not found")

    from src.services.url_ingestion import fetch_url_content

    try:
        title, text = await fetch_url_content(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(422, f"HTTP error fetching URL: {exc.response.status_code}")
    except httpx.HTTPError as exc:
        raise HTTPException(422, f"Failed to fetch URL: {exc}")

    text_bytes = text.encode("utf-8")
    kf = KnowledgeFile(
        id=str(uuid.uuid4()),
        kb_id=kb_id,
        org_id=org_id,
        filename=title[:500],
        content_type="text/html",
        size_bytes=len(text_bytes),
        status="pending",
        source_url=url,
    )
    db.add(kf)
    await db.commit()
    await db.refresh(kf)

    # Background ingest — reuse the same chunking + embedding pipeline as file upload
    from src.services.knowledge_ingest import ingest_file
    asyncio.create_task(ingest_file(kf.id, org_id, kb_id, text_bytes, "text/plain", kf.filename))

    return URLIngestResponse(ok=True, file_id=kf.id, title=title, chars=len(text))


# ── Semantic search ────────────────────────────────────────────────────────────

@router.get("/{kb_id}/search", response_model=list[ChunkResult])
async def search_kb(
    kb_id: str,
    q: str = Query(..., min_length=1),
    top_k: int = Query(default=5, ge=1, le=20),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0,
                             description="Drop results scoring below this (#206)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.viewer, db)
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == org_id))
    if not r.scalar_one_or_none():
        raise HTTPException(404, "Knowledge base not found")

    from src.services.embeddings import embed, _cosine, _keyword_score

    query_vec = await embed(q, org_id)

    # #201: indexed ANN fast path via pgvector. When available, rank with the
    # `<=>` index instead of loading + scoring every chunk in Python. Falls
    # through to the Python-cosine path below if unavailable or empty.
    if query_vec:
        from src.services.vector_search import search_kb_chunks
        ann = await search_kb_chunks(db, kb_id, query_vec, top_k, min_score)
        if ann:
            by_id = {
                c.id: c for c in (await db.execute(
                    select(KnowledgeChunk).where(KnowledgeChunk.id.in_([cid for cid, _ in ann]))
                )).scalars().all()
            }
            fids = {c.file_id for c in by_id.values()}
            fmap: dict[str, str] = {}
            if fids:
                fr = await db.execute(select(KnowledgeFile).where(KnowledgeFile.id.in_(fids)))
                fmap = {f.id: f.filename for f in fr.scalars().all()}
            out = []
            for cid, score in ann:
                c = by_id.get(cid)
                if not c:
                    continue
                out.append(ChunkResult(
                    chunk_id=c.id, file_id=c.file_id,
                    filename=fmap.get(c.file_id, "unknown"),
                    content=c.content, score=round(score, 4),
                    chunk_index=c.chunk_index,
                ))
            return out

    cr = await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb_id))
    chunks = cr.scalars().all()

    # Map file_id → filename
    file_ids = {c.file_id for c in chunks}
    fname_map: dict[str, str] = {}
    if file_ids:
        fr = await db.execute(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))
        for f in fr.scalars().all():
            fname_map[f.id] = f.filename

    scored = []
    for chunk in chunks:
        emb = chunk.embedding
        if query_vec and emb and len(emb) == len(query_vec):
            score = _cosine(query_vec, emb)
        else:
            score = _keyword_score(q, chunk.content)
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    # #206: drop low-relevance noise so a high top_k doesn't return junk.
    return [
        ChunkResult(
            chunk_id=c.id, file_id=c.file_id,
            filename=fname_map.get(c.file_id, "unknown"),
            content=c.content, score=round(score, 4),
            chunk_index=c.chunk_index,
        )
        for score, c in scored[:top_k]
        if score >= min_score
    ]
