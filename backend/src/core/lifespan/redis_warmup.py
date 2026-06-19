import logging

from src.core.redis import get_redis

logger = logging.getLogger(__name__)


async def startup_redis():
    redis = get_redis()
    await redis.ping()
    logger.info("Redis connected")

    try:
        from src.seeding.seed_orgs import seed_all
        await seed_all()
        logger.info("Skills seeded")
    except Exception as exc:
        logger.warning(f"Skills seed failed (non-fatal): {exc}")
