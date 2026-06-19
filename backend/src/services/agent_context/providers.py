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
