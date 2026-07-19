"""Capability-based provider selection for auxiliary pipelines.

Chat turns route through the resolver + `router.stream_response`; auxiliary
pipelines (embeddings, speech-to-text, image description) need a *specific API
capability* rather than a chat model. Which provider types support which
capability — and with which model — is DATA, declared in each provider seed's
`capabilities` block (`seeds/providers/.../provider.json`), never a hardcoded
type list in service code:

    "capabilities": {
      "embeddings": {"model": "text-embedding-3-small", "dimensions": 1536},
      "stt":        {"model": "whisper-1"},
      "vision":     {"model": "gpt-4o-mini", "api": "openai_compat"}
    }

`api` names the SDK wire format the capability call must use (defaults to the
seed's `stream_type`). Custom seeds override builtin ones per the loader's
normal precedence, so deployments can re-point models without code changes.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.provider import Provider

logger = logging.getLogger(__name__)


def get_capability(provider_type: str, capability: str) -> dict | None:
    """The seed-declared capability config for a provider type, or None.
    Resolves `api` from the seed's stream_type when not set explicitly."""
    from src.seeds.loader import get_provider as _get_pdef
    pdef = _get_pdef(provider_type) or {}
    cap = (pdef.get("capabilities") or {}).get(capability)
    if not isinstance(cap, dict):
        return None
    if "api" not in cap:
        cap = {**cap, "api": pdef.get("stream_type") or "openai_compat"}
    return cap


async def find_capability_providers(
    org_id: str, capability: str, *, limit: int = 5
) -> list[tuple[Provider, dict]]:
    """Active org providers whose seed declares `capability`, best-first
    (priority desc). Returns (Provider, capability-config) pairs; callers walk
    the list as a failover chain."""
    out: list[tuple[Provider, dict]] = []
    try:
        async with AsyncSessionLocal() as db:
            r = await db.execute(
                select(Provider).where(
                    Provider.org_id == org_id,
                    Provider.is_active.is_(True),
                ).order_by(Provider.priority.desc())
            )
            for p in r.scalars().all():
                cap = get_capability(p.provider_type, capability)
                if cap:
                    out.append((p, cap))
                    if len(out) >= limit:
                        break
    except Exception as exc:
        logger.warning("[capabilities] lookup failed for %s: %s", capability, exc)
    return out


def provider_api_key(provider: Provider) -> str:
    """Decrypted api key/token for a provider row ('' when absent)."""
    try:
        from src.providers.router import _get_credentials
        creds = _get_credentials(provider)
        return creds.get("api_key") or creds.get("token") or ""
    except Exception:
        return ""


def provider_base_url(provider: Provider) -> str | None:
    """Effective base URL: the row's own, else the seed default."""
    if provider.base_url:
        return provider.base_url
    from src.seeds.loader import get_provider as _get_pdef
    return (_get_pdef(provider.provider_type) or {}).get("base_url")
