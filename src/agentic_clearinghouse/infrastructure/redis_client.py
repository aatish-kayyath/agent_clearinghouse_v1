"""Redis client for idempotency keys, rate limiting, and caching.

Usage:
    from agentic_clearinghouse.infrastructure.redis_client import get_redis, close_redis

    redis = get_redis()
    await redis.set("key", "value", ex=3600)
"""

from __future__ import annotations

import redis.asyncio as aioredis

from agentic_clearinghouse.config import get_settings
from agentic_clearinghouse.logging_config import get_logger

logger = get_logger(__name__)

_redis_client: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """Initialize and return the Redis client. Called during app startup."""
    global _redis_client
    settings = get_settings()
    _redis_client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    # Verify connectivity
    await _redis_client.ping()
    logger.info("redis.connected", url=settings.redis_url)
    return _redis_client


def get_redis() -> aioredis.Redis:
    """Return the Redis client singleton. Must call init_redis() first."""
    if _redis_client is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection. Called during app shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        logger.info("redis.disconnected")
        _redis_client = None


# --- Idempotency Helpers ---


async def check_idempotency(key: str) -> bool:
    """Check if an idempotency key has already been used.

    Returns True if the key exists (duplicate), False if new.
    """
    redis = get_redis()
    return bool(await redis.exists(f"idempotency:{key}"))


async def set_idempotency(key: str, value: str = "1") -> None:
    """Mark an idempotency key as used with a TTL."""
    settings = get_settings()
    redis = get_redis()
    await redis.set(
        f"idempotency:{key}",
        value,
        ex=settings.redis_idempotency_ttl_seconds,
    )
