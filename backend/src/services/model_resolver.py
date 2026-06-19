"""Resolve a ModelProfile to a list of (Provider, model_name) pairs for LLM routing."""
import logging
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.model_profile import ModelProfile
from src.models.provider import Provider

logger = logging.getLogger(__name__)


async def resolve_providers_for_profile(
    profile_id: str,
    org_id: str | None,
) -> list[tuple[Provider, str | None]] | None:
    """Return providers for a model profile, or None if not found/inactive.

    Resolution order:
      1. provider_type set → all active org accounts of that type (enables automatic rotation)
      2. provider_chain_id set → explicit fallback chain
    """
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(ModelProfile).where(ModelProfile.id == profile_id))
        profile = r.scalar_one_or_none()
        if not profile or not profile.is_active:
            logger.debug(f"[model_resolver] profile {profile_id} not found or inactive")
            return None

        provider_type = profile.provider_type
        chain_id = profile.provider_chain_id
        model_name_override = profile.model_name

    if provider_type and org_id:
        async with AsyncSessionLocal() as db:
            r = await db.execute(
                select(Provider)
                .where(
                    Provider.org_id == org_id,
                    Provider.provider_type == provider_type,
                    Provider.is_active == True,  # noqa: E712
                )
                .order_by(Provider.name)
            )
            providers = r.scalars().all()
        if providers:
            logger.debug(
                f"[model_resolver] profile {profile_id} → type '{provider_type}' "
                f"→ {len(providers)} account(s), model={model_name_override}"
            )
            return [(p, model_name_override) for p in providers]
        logger.warning(f"[model_resolver] no active accounts for provider_type='{provider_type}' in org {org_id}")
        return None

    if chain_id:
        from src.services.agent_context import get_chain_providers
        providers = await get_chain_providers(chain_id, org_id)
        logger.debug(f"[model_resolver] profile {profile_id} resolved via chain {chain_id}: {len(providers)} providers")
        return providers or None

    logger.warning(f"[model_resolver] profile {profile_id} has no provider_type or chain configured")
    return None


async def resolve_best_profile_by_tags(
    org_id: str,
    tags: list[str],
) -> ModelProfile | None:
    """Return the active profile with the most tag overlap."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(ModelProfile)
            .where(ModelProfile.org_id == org_id, ModelProfile.is_active == True)  # noqa: E712
            .order_by(ModelProfile.name)
        )
        profiles = r.scalars().all()

    tag_set = set(tags)
    best: ModelProfile | None = None
    best_score = -1
    for p in profiles:
        score = len(set(p.tags or []) & tag_set)
        if score > best_score:
            best_score = score
            best = p

    return best if best_score >= 0 else None
