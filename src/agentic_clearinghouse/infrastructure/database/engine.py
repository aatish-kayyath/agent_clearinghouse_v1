"""Async database engine and session management.

Provides:
    - async_engine: The SQLAlchemy async engine (singleton).
    - AsyncSessionFactory: A sessionmaker bound to the engine.
    - get_async_session: FastAPI dependency that yields a session per request.
    - init_db / close_db: Lifecycle hooks for FastAPI's lifespan.

Usage in FastAPI:
    @app.get("/contracts")
    async def list_contracts(session: AsyncSession = Depends(get_async_session)):
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agentic_clearinghouse.config import get_settings
from agentic_clearinghouse.logging_config import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = get_logger(__name__)

# Module-level singletons (initialized in init_db)
_engine = None
_session_factory = None


def _get_engine():
    """Get or create the async engine (lazy singleton)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_pre_ping=True,
            echo=settings.db_echo_sql,
        )
        logger.info(
            "database.engine_created",
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the session factory (lazy singleton)."""
    global _session_factory
    if _session_factory is None:
        engine = _get_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    The session is automatically committed on success or rolled back on error.
    """
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize the database engine and create tables if they don't exist.

    Called during FastAPI's lifespan startup. In production, use Alembic
    migrations instead of create_all.
    """
    from agentic_clearinghouse.infrastructure.database.orm_models import Base

    engine = _get_engine()
    settings = get_settings()

    if settings.is_development:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("database.tables_created")
    else:
        logger.info("database.skipping_create_all", reason="not in development mode")


async def close_db() -> None:
    """Dispose of the database engine. Called during FastAPI's lifespan shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("database.engine_disposed")
        _engine = None
        _session_factory = None
