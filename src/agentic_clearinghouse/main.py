"""FastAPI application entry point for the Agentic Clearinghouse.

Lifecycle:
    1. Startup: Initialize logging, database, Redis, create tables (dev mode).
    2. Running: Serve REST API + MCP tools on a single Uvicorn process.
    3. Shutdown: Close database and Redis connections gracefully.

The MCP server is mounted at /mcp so AI agents can discover tools
alongside the REST API at /api/v1/*.

Run with:
    uv run uvicorn agentic_clearinghouse.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from agentic_clearinghouse.config import get_settings
from agentic_clearinghouse.logging_config import get_logger, setup_logging

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    settings = get_settings()

    # 1. Setup structured logging
    setup_logging(
        log_level=settings.app_log_level,
        json_logs=not settings.is_development,
    )
    logger = get_logger(__name__)
    logger.info(
        "app.starting",
        env=settings.app_env,
        debug=settings.app_debug,
    )

    # 2. Initialize database
    from agentic_clearinghouse.infrastructure.database.engine import close_db, init_db

    await init_db()

    # 3. Initialize Redis
    from agentic_clearinghouse.infrastructure.redis_client import close_redis, init_redis

    try:
        await init_redis()
    except Exception as exc:
        logger.warning("app.redis_unavailable", error=str(exc))

    logger.info("app.started", host=settings.app_host, port=settings.app_port)

    yield

    # Shutdown
    logger.info("app.shutting_down")
    await close_db()
    await close_redis()
    logger.info("app.stopped")


def create_app() -> FastAPI:
    """Application factory — creates and configures the FastAPI app."""
    settings = get_settings()

    app = FastAPI(
        title="Agentic Clearinghouse",
        description=(
            "Escrow & verification protocol for AI agents. "
            "Trust Code, Not Agents."
        ),
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.app_debug,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    # --- Middleware ---
    from agentic_clearinghouse.api.middleware import setup_middleware

    setup_middleware(app)

    # --- REST API Routes ---
    from agentic_clearinghouse.api.routes.escrow import router as escrow_router
    from agentic_clearinghouse.api.routes.health import router as health_router

    app.include_router(health_router)
    app.include_router(escrow_router)

    # --- MCP Server (mounted as sub-application) ---
    from agentic_clearinghouse.mcp_server.tools import mcp

    mcp_app = mcp.sse_app()
    app.mount("/mcp", mcp_app)

    return app


# The app instance used by Uvicorn
app = create_app()
