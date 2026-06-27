"""Provider and chain resolution helpers."""
import logging
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.project import Project
from src.models.provider import Provider, ProviderChain, ProviderChainItem

logger = logging.getLogger(__name__)


async def _round_robin(accounts: list, org_id: str | None, provider_type: str) -> list:
    """Rotate equal accounts of one provider-type so load spreads across them.

    Failover order across provider TYPES is preserved (chain position); only the
    starting account within a type group rotates, via a per-(org, type) Redis
    counter that advances on each chain expansion. Falls back to stable order if
    Redis is unavailable.
    """
    n = len(accounts)
    if n <= 1 or not org_id:
        return accounts
    try:
        from src.core.redis import get_redis
        redis = get_redis()
        c = await redis.incr(f"pchain:rr:{org_id}:{provider_type}")
        off = (int(c) - 1) % n
    except Exception as exc:
        logger.debug("[provider-chain] round-robin offset failed, using stable order: %s", exc)
        off = 0
    return accounts[off:] + accounts[:off]


async def get_chain_providers(chain_id: str | None, org_id: str | None) -> list[tuple[Provider, str | None]]:
    """Resolve a chain to an ordered list of (Provider account, model_name) pairs.

    Each chain step stores a provider_type + optional model_name.  All active
    accounts of that type in the org are expanded into consecutive pairs so
    stream_response() can rotate across accounts on rate-limit within a step.
    """
    async with AsyncSessionLocal() as db:
        if chain_id:
            # Derive org_id from the chain itself if not supplied
            if not org_id:
                r = await db.execute(select(ProviderChain).where(ProviderChain.id == chain_id))
                ch = r.unique().scalar_one_or_none()
                if ch:
                    org_id = ch.org_id

            result = await db.execute(
                select(ProviderChainItem)
                .where(ProviderChainItem.chain_id == chain_id)
                .order_by(ProviderChainItem.position)
            )
            items = result.scalars().all()
            pairs: list[tuple[Provider, str | None]] = []
            for item in items:
                r2 = await db.execute(
                    select(Provider)
                    .where(
                        Provider.org_id == org_id,
                        Provider.provider_type == item.provider_type,
                        Provider.is_active == True,  # noqa: E712
                    )
                    .order_by(Provider.name)
                )
                accounts = await _round_robin(list(r2.scalars().all()), org_id, item.provider_type)
                for account in accounts:
                    pairs.append((account, item.model_name))
            return pairs

        if org_id:
            result = await db.execute(
                select(ProviderChain).where(
                    ProviderChain.org_id == org_id,
                    ProviderChain.is_default == True  # noqa: E712
                ).limit(1)
            )
            chain = result.unique().scalar_one_or_none()

            # No default chain (or we have one but still want profiles as extra fallback)
            # — try all active model profiles in priority order first.
            from src.models.model_profile import ModelProfile
            mp_r = await db.execute(
                select(ModelProfile)
                .where(ModelProfile.org_id == org_id, ModelProfile.is_active == True)  # noqa: E712
                .order_by(ModelProfile.priority.desc())
            )
            profiles = mp_r.scalars().all()

            all_providers_result = await db.execute(
                select(Provider)
                .where(Provider.org_id == org_id, Provider.is_active == True)  # noqa: E712
                .order_by(Provider.priority.desc())
            )
            all_providers = [(p, None) for p in all_providers_result.scalars().all()]

            if profiles:
                from src.services.model_resolver import resolve_providers_for_profile
                combined: list[tuple[Provider, str | None]] = []
                for profile in profiles:
                    profile_providers = await resolve_providers_for_profile(profile.id, org_id)
                    if profile_providers:
                        combined.extend(profile_providers)
                if combined:
                    # Append default chain providers as final fallback (deduped by provider id)
                    if chain:
                        chain_pairs = await get_chain_providers(chain.id, org_id)
                        seen = {p.id for p, _ in combined}
                        combined.extend((p, m) for p, m in chain_pairs if p.id not in seen)
                    return combined
                # Profiles configured but none resolved → fall through to chain / all providers

            if chain:
                return await get_chain_providers(chain.id, org_id)

            return all_providers

    return []


async def get_effective_chain_id(chat: Chat | None) -> str | None:
    if not chat:
        return None
    if chat.provider_chain_id:
        return chat.provider_chain_id
    if not chat.project_id:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == chat.project_id))
        project = result.unique().scalar_one_or_none()
        if not project:
            return None
        return project.provider_chain_id


def _fmt_remaining(seconds: int) -> str:
    """Human '2h 16m' / '45s' for a cooldown remaining-time."""
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


async def provider_availability(org_id: str | None, db=None) -> list[dict]:
    """Per-account availability snapshot for the org's active providers.

    Returns ``[{name, provider_type, model, available, cooling, remaining_seconds,
    remaining_human, reason}]`` — the durable state every caller (UI, agents,
    resolver) reads to know "can we work now, and if not, when". An account is
    available when active and not durably cooling. Pass ``db`` to reuse an open
    session (e.g. a request's injected session); omit it to open a fresh one.
    """
    from datetime import datetime, timezone
    out: list[dict] = []
    if not org_id:
        return out
    _q = (
        select(Provider).where(Provider.org_id == org_id, Provider.is_active == True)  # noqa: E712
        .order_by(Provider.provider_type, Provider.name)
    )
    if db is not None:
        rows = (await db.execute(_q)).scalars().all()
    else:
        async with AsyncSessionLocal() as _db:
            rows = (await _db.execute(_q)).scalars().all()
    now = datetime.now(timezone.utc)
    for p in rows:
        cu = p.cooling_until
        remaining = 0
        if cu:
            if cu.tzinfo is None:
                cu = cu.replace(tzinfo=timezone.utc)
            remaining = max(0, int((cu - now).total_seconds()))
        cooling = remaining > 0
        out.append({
            "name": p.name,
            "provider_type": p.provider_type,
            "model": p.model_name,
            "available": not cooling,
            "cooling": cooling,
            "remaining_seconds": remaining,
            "remaining_human": _fmt_remaining(remaining) if cooling else "",
            "reason": (p.last_error or "")[:120] if cooling else "",
        })
    return out


async def provider_availability_summary(org_id: str | None, db=None) -> str:
    """Compact one-block summary of provider availability for agent context.

    Empty string when nothing is cooling (no need to spend tokens telling an agent
    everything is fine). When something IS cooling, agents see which accounts are
    usable now and when the limited ones come back, so they route delegation to a
    live provider instead of stalling on an exhausted one.
    """
    snap = await provider_availability(org_id, db=db)
    if not snap:
        return ""
    cooling = [s for s in snap if s["cooling"]]
    if not cooling:
        return ""  # all good — stay quiet
    avail = [s for s in snap if s["available"]]
    lines = ["## Provider availability", ""]
    if avail:
        lines.append("Usable now: " + ", ".join(
            f"{s['name']} ({s['provider_type']})" for s in avail
        ))
    else:
        lines.append("No provider is usable right now — every account is cooling down.")
    for s in cooling:
        lines.append(f"- {s['name']} ({s['provider_type']}) cooling, back in ~{s['remaining_human']}")
    lines.append("")
    lines.append("Prefer a usable provider when delegating; avoid the cooling ones until they reset.")
    return "\n".join(lines)


async def get_direct_provider(chat: Chat | None) -> list[tuple[Provider, str | None]]:
    """Return a single-provider list if the chat has a direct_provider_id set."""
    if not chat:
        return []
    pid = getattr(chat, "direct_provider_id", None)
    if not pid:
        return []
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Provider).where(Provider.id == pid))
        p = result.scalar_one_or_none()
        return [(p, None)] if p else []
