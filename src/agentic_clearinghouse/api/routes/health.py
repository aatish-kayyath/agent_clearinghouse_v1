"""Health check endpoint.

Verifies connectivity to PostgreSQL and Redis, returns structured status.
Used by Docker healthchecks, load balancers, and monitoring systems.
"""

from __future__ import annotations

from fastapi import APIRouter

from agentic_clearinghouse.logging_config import get_logger
from agentic_clearinghouse.schemas.escrow import HealthResponse

router = APIRouter(tags=["Health"])
logger = get_logger(__name__)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the health status of the application and its dependencies.",
)
async def health_check() -> HealthResponse:
    """Check connectivity to PostgreSQL and Redis."""
    db_status = "unknown"
    redis_status = "unknown"

    # Check PostgreSQL
    try:
        from agentic_clearinghouse.infrastructure.database.engine import _get_engine

        engine = _get_engine()
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "healthy"
    except Exception as exc:
        db_status = f"unhealthy: {exc}"
        logger.error("health.db_check_failed", error=str(exc))

    # Check Redis
    try:
        from agentic_clearinghouse.infrastructure.redis_client import get_redis

        redis = get_redis()
        await redis.ping()
        redis_status = "healthy"
    except Exception as exc:
        redis_status = f"unhealthy: {exc}"
        logger.error("health.redis_check_failed", error=str(exc))

    overall = "ok" if db_status == "healthy" and redis_status == "healthy" else "degraded"

    return HealthResponse(
        status=overall,
        version="0.1.0",
        database=db_status,
        redis=redis_status,
    )
