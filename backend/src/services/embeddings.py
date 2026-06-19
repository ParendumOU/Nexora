"""Embedding service — generate and search float vectors for semantic memory.

Uses the org's first active OpenAI-compatible provider to generate embeddings.
Falls back to keyword overlap scoring when no suitable provider is configured.
"""
from __future__ import annotations
import math
import logging
from typing import Sequence

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_EMBED_DIM = 1536


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _keyword_score(query: str, content: str) -> float:
    qwords = set(query.lower().split())
    cwords = set(content.lower().split())
    if not qwords:
        return 0.0
    return len(qwords & cwords) / len(qwords)


async def _get_openai_client(org_id: str):
    """Return (AsyncOpenAI client, model) for the org's first active openai-compat provider, or None."""
    try:
        import json
        from sqlalchemy import select
        from src.core.database import AsyncSessionLocal
        from src.core.security import decrypt
        from src.models.provider import Provider

        async with AsyncSessionLocal() as db:
            r = await db.execute(
                select(Provider).where(
                    Provider.org_id == org_id,
                    Provider.is_active == True,  # noqa: E712
                    Provider.provider_type.in_(["openai", "openrouter", "groq", "together", "gemini-api"]),
                ).limit(1)
            )
            provider = r.scalar_one_or_none()

        if not provider or not provider.credentials:
            return None, None

        creds = json.loads(decrypt(provider.credentials))
        api_key = creds.get("api_key", "")
        if not api_key:
            return None, None

        from openai import AsyncOpenAI
        from src.seeds.loader import get_provider as _get_pdef
        pdef = _get_pdef(provider.provider_type) or {}
        base_url = provider.base_url or pdef.get("base_url")
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        return client, _EMBED_MODEL
    except Exception as exc:
        logger.debug("Could not get embedding client: %s", exc)
        return None, None


async def embed(text: str, org_id: str) -> list[float] | None:
    """Return embedding vector for text, or None if no provider available."""
    client, model = await _get_openai_client(org_id)
    if not client:
        return None
    try:
        resp = await client.embeddings.create(model=model, input=text[:8000])
        return resp.data[0].embedding
    except Exception as exc:
        logger.warning("Embedding failed: %s", exc)
        return None


def semantic_search(
    query_vec: list[float] | None,
    query_text: str,
    memories: Sequence,
    top_k: int = 10,
    threshold: float = 0.3,
) -> list:
    """Rank memories by cosine similarity (or keyword overlap as fallback).

    Returns up to top_k memories above threshold, sorted by score desc.
    """
    scored = []
    for mem in memories:
        emb = getattr(mem, "embedding", None)
        if query_vec and emb and len(emb) == len(query_vec):
            score = _cosine(query_vec, emb)
        else:
            score = _keyword_score(query_text, mem.content)
        if score >= threshold:
            scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [mem for _, mem in scored[:top_k]]
