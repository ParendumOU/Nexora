"""Knowledge search tool — semantic search across org knowledge bases."""
from __future__ import annotations
import logging
from src.core.pubsub import broadcast as _broadcast
# Module-level so tests can patch it (and prod binds the real factory at import).
from src.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _get_org_id(chat_id: str) -> str | None:
    """Resolve the org for a knowledge_search call.

    Walks the parent_chat_id chain (a delegated sub-agent runs in a sub-chat OWNED BY
    THE SYSTEM USER, so the old user-OrgMember fallback resolved the wrong org and the
    search hit an empty KB). At each level the chat's own agent carries the correct
    org (the per-org agent copy the task spawned), so that is the primary signal;
    project org is next; only at the human-owned root do we fall back to the user's
    active org / membership."""
    from sqlalchemy import select
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.org import OrgMember
    from src.models.agent import Agent
    from src.models.user import User

    async with AsyncSessionLocal() as db:
        visited: set[str] = set()
        cur_id = chat_id
        root_user_id: str | None = None
        while cur_id and cur_id not in visited:
            visited.add(cur_id)
            chat = (await db.execute(select(Chat).where(Chat.id == cur_id))).scalar_one_or_none()
            if not chat:
                break
            # The chat's assigned agent is org-scoped → most reliable for a sub-agent.
            if chat.agent_id:
                ag = (await db.execute(select(Agent).where(Agent.id == chat.agent_id))).scalar_one_or_none()
                if ag and ag.org_id:
                    return ag.org_id
            if chat.project_id:
                proj = (await db.execute(select(Project).where(Project.id == chat.project_id))).unique().scalar_one_or_none()
                if proj and proj.org_id:
                    return proj.org_id
            root_user_id = chat.user_id or root_user_id
            if not chat.parent_chat_id:
                break
            cur_id = chat.parent_chat_id

        # Root fallback: the human owner's active org, else their first membership.
        if root_user_id:
            u = (await db.execute(select(User).where(User.id == root_user_id))).scalar_one_or_none()
            if u and u.active_org_id:
                return u.active_org_id
            m = (await db.execute(select(OrgMember).where(OrgMember.user_id == root_user_id).limit(1))).scalar_one_or_none()
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

        # #201: indexed ANN fast path when pgvector is available.
        ann = None
        if query_vec:
            from src.services.vector_search import search_chunks
            ann = await search_chunks(db, kb_ids, query_vec, top_k)
        if ann:
            by_id = {
                c.id: c for c in (await db.execute(
                    select(KnowledgeChunk).where(KnowledgeChunk.id.in_([cid for cid, _ in ann]))
                )).scalars().all()
            }
            fids = {c.file_id for c in by_id.values()}
            fmap2: dict[str, str] = {}
            if fids:
                fr = await db.execute(select(KnowledgeFile).where(KnowledgeFile.id.in_(fids)))
                fmap2 = {f.id: f.filename for f in fr.scalars().all()}
            results = []
            for cid, score in ann:
                c = by_id.get(cid)
                if not c:
                    continue
                results.append({
                    "kb_id": c.kb_id, "kb_name": kb_name_map.get(c.kb_id, ""),
                    "file_id": c.file_id, "filename": fmap2.get(c.file_id, "unknown"),
                    "content": c.content, "score": round(score, 4),
                    "chunk_index": c.chunk_index,
                })
            return {"data": {"results": results, "count": len(results)}}

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
