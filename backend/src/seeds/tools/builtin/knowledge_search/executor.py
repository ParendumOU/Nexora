"""Knowledge search tool — semantic search across org knowledge bases."""
from __future__ import annotations
import logging
from src.core.pubsub import broadcast as _broadcast

logger = logging.getLogger(__name__)


async def _get_org_id(chat_id: str) -> str | None:
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.org import OrgMember

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = r.scalar_one_or_none()
        if not chat:
            return None
        if chat.project_id:
            rp = await db.execute(select(Project).where(Project.id == chat.project_id))
            proj = rp.unique().scalar_one_or_none()
            if proj:
                return proj.org_id
        # Fall back to user's active org
        if chat.user_id:
            rm = await db.execute(select(OrgMember).where(OrgMember.user_id == chat.user_id).limit(1))
            m = rm.scalar_one_or_none()
            if m:
                return m.org_id
    return None


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}

    kb_id = args.get("kb_id")
    top_k = min(int(args.get("top_k") or 5), 20)

    org_id = await _get_org_id(chat_id)
    if not org_id:
        return {"error": "Could not determine org for this chat"}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "knowledge_search", "label": f"Searching knowledge base…",
    })

    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.knowledge_base import KnowledgeBase, KnowledgeFile, KnowledgeChunk
    from src.services.embeddings import embed, _cosine, _keyword_score

    query_vec = await embed(query, org_id)

    async with AsyncSessionLocal() as db:
        # Get all target KBs
        if kb_id:
            kbr = await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == org_id)
            )
            kbs = kbr.scalars().all()
        else:
            kbr = await db.execute(select(KnowledgeBase).where(KnowledgeBase.org_id == org_id))
            kbs = kbr.scalars().all()

        if not kbs:
            return {"data": {"results": [], "message": "No knowledge bases found for this org"}}

        kb_ids = [kb.id for kb in kbs]
        kb_name_map = {kb.id: kb.name for kb in kbs}

        cr = await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.kb_id.in_(kb_ids)))
        chunks = cr.scalars().all()

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
            score = _keyword_score(query, chunk.content)
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [
        {
            "kb_id": c.kb_id,
            "kb_name": kb_name_map.get(c.kb_id, ""),
            "file_id": c.file_id,
            "filename": fname_map.get(c.file_id, "unknown"),
            "content": c.content,
            "score": round(score, 4),
            "chunk_index": c.chunk_index,
        }
        for score, c in scored[:top_k]
    ]
    return {"data": {"results": results, "count": len(results)}}
