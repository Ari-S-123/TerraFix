"""
Structured logging configuration for TerraFix.

This module provides structured JSON logging with correlation IDs for
request tracing. All logs include standard fields (timestamp, level,
logger, correlation_id) plus context-specific fields.

Log Format:
    {
        "timestamp": "2025-11-14T10:30:00.123Z",
        "level": "INFO",
        "logger": "terrafix.vanta_client",
        "correlation_id": "abc123...",
        "message": "Fetching failing tests from Vanta",
        "test_id": "vanta-test-456",
        "failure_hash": "def789...",
        ...additional context...
    }

Usage:
    from terrafix.logging_config import setup_logging, get_logger, log_with_context

    # Initialize logging (call once at startup)
    setup_logging(log_level="INFO")

    # Get logger for module
    logger = get_logger(__name__)

    # Log with context
    log_with_context(
        logger,
        "info",
        "Processing failure",
        correlation_id=correlation_id,
        test_id=failure.test_id,
        resource_arn=failure.resource_arn,
    )
"""

import json
import logging
import sys
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from types import TracebackType
from typing import override

# Context variable for correlation ID that propagates through async/sync calls
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter that outputs structured JSON logs.

    Each log record is formatted as a JSON object with standard fields
    plus any extra fields from the LogRecord. This enables easy parsing
    and querying in log aggregation systems like CloudWatch Logs Insights.

    Standard Fields:
        - timestamp: ISO 8601 timestamp in UTC
        - level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        - logger: Logger name (usually module path)
        - correlation_id: Request correlation ID for tracing
        - message: Human-readable log message
        - exc_info: Exception information if present

    Additional fields are included from the LogRecord extras.
    """

    @override
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON string representation of log record
        """
        # Build base log entry
        log_entry: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": _correlation_id.get(),
            "message": record.getMessage(),
        }

        # Add exception information if present
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        # Add any extra fields from the record
        # Skip standard LogRecord attributes to avoid duplication
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
        }

        for key, value in record.__dict__.items():
            record_value: object = value
            if key not in standard_attrs and not key.startswith("_"):
                log_entry[key] = record_value

        return json.dumps(log_entry)


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure structured logging for TerraFix.

    Sets up JSON logging to stdout with the specified log level.
    Should be called once at application startup.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Example:
        >>> setup_logging("INFO")
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler with structured formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(StructuredFormatter())

    # Add handler to root logger
    root_logger.addHandler(console_handler)

    # Set logging level for noisy libraries
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("github").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get logger for a module.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing started")
    """
    return logging.getLogger(name)


def generate_correlation_id() -> str:
    """
    Generate a new correlation ID.

    Correlation IDs are UUIDs used to trace a single failure through
    the entire pipeline (Vanta fetch → parsing → Bedrock → GitHub PR).

    Returns:
        UUID string to use as correlation ID

    Example:
        >>> correlation_id = generate_correlation_id()
        >>> set_correlation_id(correlation_id)
    """
    return str(uuid.uuid4())


def set_correlation_id(correlation_id: str) -> None:
    """
    Set correlation ID for current context.

    The correlation ID will be included in all subsequent log messages
    within this context. For async code, the correlation ID propagates
    automatically through context vars.

    Args:
        correlation_id: Correlation ID to set

    Example:
        >>> correlation_id = generate_correlation_id()
        >>> set_correlation_id(correlation_id)
        >>> logger.info("This log will include correlation_id")
    """
    _ = _correlation_id.set(correlation_id)


def get_correlation_id() -> str | None:
    """
    Get current correlation ID.

    Returns:
        Current correlation ID or None if not set

    Example:
        >>> correlation_id = get_correlation_id()
        >>> if correlation_id:
        ...     print(f"Current request: {correlation_id}")
    """
    return _correlation_id.get()


def clear_correlation_id() -> None:
    """
    Clear correlation ID from current context.

    Should be called after processing is complete to avoid
    correlation ID leaking into unrelated operations.

    Example:
        >>> clear_correlation_id()
    """
    _ = _correlation_id.set(None)


def log_with_context(
    logger: logging.Logger,
    level: str,
    message: str,
    **context: object,
) -> None:
    """
    Log message with additional structured context.

    This is the recommended way to emit logs with context fields.
    Context fields are added to the log entry as top-level JSON fields.

    Args:
        logger: Logger instance
        level: Log level (debug, info, warning, error, critical)
        message: Human-readable log message
        **context: Additional context fields as keyword arguments

    Example:
        >>> logger = get_logger(__name__)
        >>> log_with_context(
        ...     logger,
        ...     "info",
        ...     "Processing failure",
        ...     test_id="test-123",
        ...     resource_arn="arn:aws:s3:::bucket",
        ...     severity="high",
        ... )
    """
    log_func: Callable[..., None] = getattr(logger, level.lower())
    log_func(message, extra=dict(context))


class LogContext:
    """
    Context manager for correlation IDs.

    Automatically generates and cleans up correlation IDs for a block of code.
    Useful for ensuring correlation IDs don't leak between operations.

    Example:
        >>> with LogContext() as correlation_id:
        ...     logger.info("This has correlation_id")
        ...     process_failure()
    """

    def __init__(self, correlation_id: str | None = None) -> None:
        """
        Initialize log context.

        Args:
            correlation_id: Optional correlation ID to use (generates new if None)
        """
        self.correlation_id: str = correlation_id or generate_correlation_id()

    def __enter__(self) -> str:
        """
        Enter context and set correlation ID.

        Returns:
            Correlation ID for this context
        """
        set_correlation_id(self.correlation_id)
        return self.correlation_id

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """
        Exit context and clear correlation ID.

        Args:
            exc_type: Exception type if raised
            exc_val: Exception value if raised
            exc_tb: Exception traceback if raised
        """
        clear_correlation_id()
