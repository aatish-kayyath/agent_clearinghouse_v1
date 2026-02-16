"""FastAPI middleware for request tracing, error handling, and CORS.

Middleware stack (applied bottom-up):
    1. RequestIDMiddleware — injects X-Request-ID into every request/response
    2. ErrorHandlerMiddleware — catches domain exceptions -> structured JSON errors
    3. CORSMiddleware — handles browser-based MCP clients (if any)
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from agentic_clearinghouse.domain.exceptions import (
    ClearinghouseError,
    ContractNotFoundError,
    DuplicateOperationError,
    InvalidStateTransitionError,
)

if TYPE_CHECKING:
    from fastapi import FastAPI, Request, Response

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 1. Request ID Middleware
# ---------------------------------------------------------------------------
class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject a unique X-Request-ID into every request for log correlation."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Use client-provided ID or generate one
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # Bind to structlog context for all log entries in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# 2. Error Handler Middleware
# ---------------------------------------------------------------------------
class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Catch domain exceptions and return structured JSON error responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            return await call_next(request)
        except ContractNotFoundError as exc:
            logger.warning("contract.not_found", error=exc.message)
            return JSONResponse(
                status_code=404,
                content={"error": exc.code, "message": exc.message},
            )
        except InvalidStateTransitionError as exc:
            logger.warning(
                "state_machine.invalid_transition",
                current=exc.current_state,
                attempted=exc.attempted_state,
            )
            return JSONResponse(
                status_code=409,
                content={"error": exc.code, "message": exc.message},
            )
        except DuplicateOperationError as exc:
            logger.warning("idempotency.duplicate", error=exc.message)
            return JSONResponse(
                status_code=409,
                content={"error": exc.code, "message": exc.message},
            )
        except ClearinghouseError as exc:
            logger.error("domain.error", error=exc.message, code=exc.code)
            return JSONResponse(
                status_code=400,
                content={"error": exc.code, "message": exc.message},
            )
        except Exception as exc:
            logger.exception("unhandled.error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={
                    "error": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                },
            )


# ---------------------------------------------------------------------------
# Setup function
# ---------------------------------------------------------------------------
def setup_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI application.

    Order matters — middleware is applied bottom-up, so the last added
    middleware runs first.
    """
    # CORS (runs first)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Error handling (runs second)
    app.add_middleware(ErrorHandlerMiddleware)

    # Request ID (runs last = outermost)
    app.add_middleware(RequestIDMiddleware)
