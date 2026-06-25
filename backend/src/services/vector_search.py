"""pgvector-backed ANN search helpers (GitLab #201).

Postgres-only fast path for KB-chunk / memory semantic search. When the `vector`
extension + an `embedding_vec` column are present, search runs as an indexed
`<=>` cosine query instead of loading every row and scoring in Python. Callers
fall back to the existing Python-cosine path (services.embeddings) when these
helpers report unavailable or return nothing.

Everything here is best-effort and guarded: on SQLite, on a Postgres without the
extension/column, or on any error, the public functions return a "not available"
signal so the caller keeps working.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_EMBED_DIM = 1536
# Cache the capability check per table for the process lifetime (the schema does
# not change at runtime). None = unknown yet.
_cap_cache: dict[str, bool] = {}


def _vec_literal(vec: list[float]) -> str:
    """pgvector text literal: '[0.1,0.2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


async def vectors_available(db: AsyncSession, table: str) -> bool:
    """True if `table.embedding_vec` exists on a Postgres with pgvector."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return False
    if table in _cap_cache:
        return _cap_cache[table]
    try:
        row = (await db.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'embedding_vec'"
        ), {"t": table})).first()
        ok = row is not None
    except Exception:
        ok = False
    _cap_cache[table] = ok
    return ok


async def store_embedding_vec(db: AsyncSession, table: str, row_id: str, vec: Optional[list]) -> None:
    """Persist a row's vector into embedding_vec (PG-only, right dimension only).
    Best-effort: silently skips when unavailable or the dimension is wrong."""
    if not vec or len(vec) != _EMBED_DIM:
        return
    if not await vectors_available(db, table):
        return
    try:
        await db.execute(
            text(f"UPDATE {table} SET embedding_vec = (:v)::vector WHERE id = :id"),
            {"v": _vec_literal(vec), "id": row_id},
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[vector_search] store failed for %s/%s: %s", table, row_id, exc)


async def search_chunks(
    db: AsyncSession, kb_ids: list[str], query_vec: list, top_k: int, min_score: float = 0.0
) -> Optional[list[tuple[str, float]]]:
    """ANN search over one or more KBs' chunks. Returns [(chunk_id, score)] sorted
    best-first, or None when the PG fast path is unavailable (caller falls back)."""
    if not query_vec or len(query_vec) != _EMBED_DIM or not kb_ids:
        return None
    if not await vectors_available(db, "knowledge_chunks"):
        return None
    try:
        rows = (await db.execute(
            text(
                "SELECT id, 1 - (embedding_vec <=> (:qv)::vector) AS score "
                "FROM knowledge_chunks "
                "WHERE kb_id = ANY(:kbs) AND embedding_vec IS NOT NULL "
                "ORDER BY embedding_vec <=> (:qv)::vector "
                "LIMIT :k"
            ),
            {"qv": _vec_literal(query_vec), "kbs": list(kb_ids), "k": top_k},
        )).all()
    except Exception as exc:
        logger.debug("[vector_search] chunk search failed: %s", exc)
        return None
    return [(r[0], float(r[1])) for r in rows if float(r[1]) >= min_score]


async def search_kb_chunks(
    db: AsyncSession, kb_id: str, query_vec: list, top_k: int, min_score: float = 0.0
) -> Optional[list[tuple[str, float]]]:
    """Single-KB convenience wrapper around search_chunks."""
    return await search_chunks(db, [kb_id], query_vec, top_k, min_score)
