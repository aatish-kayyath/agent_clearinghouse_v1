"""Structured logging configuration using structlog.

Provides JSON-structured logging in production and human-readable colored
output in development. Every log entry carries a correlation request_id
for tracing requests across the verification pipeline.

Usage:
    from agentic_clearinghouse.logging_config import setup_logging, get_logger
    setup_logging(log_level="DEBUG", json_logs=False)
    logger = get_logger()
    logger.info("escrow.created", contract_id="abc-123", amount="100.00")
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(log_level: str = "DEBUG", json_logs: bool = False) -> None:
    """Configure structlog with shared processors.

    Args:
        log_level: Standard Python log level string (DEBUG, INFO, WARNING, etc.)
        json_logs: If True, output JSON (for production). If False, colored console.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_logs:
        # Production: JSON output for log aggregation (ELK, CloudWatch, etc.)
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        # Development: colored, human-readable output
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure the standard library root logger
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.DEBUG))

    # Quiet noisy third-party loggers
    for noisy_logger in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Optional logger name. If None, uses the calling module's name.

    Returns:
        A bound structlog logger with context variable support.
    """
    return structlog.get_logger(name)
