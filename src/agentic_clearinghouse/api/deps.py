"""FastAPI dependency injection providers.

These are used with Depends() in route handlers to inject database sessions,
repositories, Redis clients, and configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends

from agentic_clearinghouse.config import Settings, get_settings
from agentic_clearinghouse.infrastructure.database.engine import get_async_session
from agentic_clearinghouse.infrastructure.database.repositories import (
    EscrowRepository,
    EventRepository,
    SubmissionRepository,
)
from agentic_clearinghouse.infrastructure.redis_client import get_redis

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for a request."""
    async for session in get_async_session():
        yield session


async def get_escrow_repo(
    session: AsyncSession = Depends(get_db_session),
) -> EscrowRepository:
    """Provide an EscrowRepository bound to the current session."""
    return EscrowRepository(session)


async def get_submission_repo(
    session: AsyncSession = Depends(get_db_session),
) -> SubmissionRepository:
    """Provide a SubmissionRepository bound to the current session."""
    return SubmissionRepository(session)


async def get_event_repo(
    session: AsyncSession = Depends(get_db_session),
) -> EventRepository:
    """Provide an EventRepository bound to the current session."""
    return EventRepository(session)


def get_redis_client() -> aioredis.Redis:
    """Provide the Redis client."""
    return get_redis()


def get_app_settings() -> Settings:
    """Provide the application settings."""
    return get_settings()
