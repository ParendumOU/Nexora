"""Embedding service — generate and search float vectors for semantic memory.

Provider selection is capability-driven: the org's active providers whose SEED
declares an `embeddings` capability (see providers/capabilities.py), best
priority first. Falls back to keyword overlap scoring when none is configured.
"""
from __future__ import annotations
import math
import logging
from typing import Sequence

logger = logging.getLogger(__name__)

# pgvector schema dimension (migration 071) — a capability whose `dimensions`
# differs is skipped, since its vectors could not be stored or compared.
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
    """(AsyncOpenAI client, model) for the org's best embeddings-capable provider,
    or (None, None). Capability + model come from the provider seed, not code."""
    try:
        from src.providers.capabilities import (
            find_capability_providers, provider_api_key, provider_base_url,
        )

        for provider, cap in await find_capability_providers(org_id, "embeddings"):
            if cap.get("dimensions") and int(cap["dimensions"]) != _EMBED_DIM:
                continue  # incompatible with the stored vector schema
            model = cap.get("model")
            api_key = provider_api_key(provider)
            if not model or not api_key:
                continue
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=api_key, base_url=provider_base_url(provider), max_retries=0,
            )
            return client, model
        return None, None
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
