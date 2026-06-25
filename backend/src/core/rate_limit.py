"""Simple Redis-backed rate limiter for FastAPI endpoints."""
from fastapi import HTTPException, Request
from src.core.redis import get_redis


async def _incr_and_check(key: str, ident: str, max_requests: int, window_seconds: int) -> bool:
    """Increment the (key, ident) counter; return True if it's now over the cap.

    Fails open (returns False) if Redis is unavailable so a Redis blip can't lock
    everyone out."""
    try:
        redis = get_redis()
        redis_key = f"ratelimit:{key}:{ident}"
        async with redis.pipeline(transaction=True) as pipe:
            await pipe.incr(redis_key)
            await pipe.expire(redis_key, window_seconds)
            results = await pipe.execute()
        return results[0] > max_requests
    except Exception:
        return False


async def rate_limit(request: Request, key: str, max_requests: int, window_seconds: int) -> None:
    """Raise HTTP 429 if the client IP exceeds max_requests in window_seconds."""
    client_ip = (request.client.host if request.client else "unknown")
    if await _incr_and_check(key, client_ip, max_requests, window_seconds):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


async def ws_rate_limit_ok(client_ip: str, key: str, max_requests: int, window_seconds: int) -> bool:
    """WebSocket variant (#168): no HTTP exception — returns False when over the cap
    so the caller can close the socket with an appropriate code."""
    return not await _incr_and_check(key, client_ip or "unknown", max_requests, window_seconds)
