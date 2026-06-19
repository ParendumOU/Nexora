"""Simple Redis-backed rate limiter for FastAPI endpoints."""
from fastapi import HTTPException, Request
from src.core.redis import get_redis


async def rate_limit(request: Request, key: str, max_requests: int, window_seconds: int) -> None:
    """Raise HTTP 429 if the client IP exceeds max_requests in window_seconds."""
    redis = get_redis()
    client_ip = (request.client.host if request.client else "unknown")
    redis_key = f"ratelimit:{key}:{client_ip}"
    async with redis.pipeline(transaction=True) as pipe:
        await pipe.incr(redis_key)
        await pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()
    count = results[0]
    if count > max_requests:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
