"""
Health check server for container orchestration.

Provides HTTP endpoints for liveness and readiness probes used by ECS,
Kubernetes, or other container orchestrators. The server runs in a
background daemon thread to avoid blocking the main service loop.

Endpoints:
    GET /health - Basic liveness check (returns 200 if server is running)
    GET /ready  - Readiness check (returns 200 if service is ready to process)
    GET /status - Detailed status with processing statistics

Usage:
    from terrafix.health_check import HealthCheckServer

    def is_ready() -> bool:
        return database_connected and api_authenticated

    def get_status() -> dict:
        return {"uptime": 3600, "processed": 42}

    server = HealthCheckServer(
        port=8080,
        readiness_check=is_ready,
        status_provider=get_status
    )
    server.start()

    # ... run main application ...

    server.stop()
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import TracebackType
from typing import ClassVar, cast, overload, override

from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


class HealthCheckHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for health check endpoints.

    Implements standard health check endpoints for container orchestration.
    Uses class-level callbacks for readiness and status information.

    Class Attributes:
        readiness_check: Optional function returning True if service is ready
        status_provider: Optional function returning status dictionary
    """

    # Class-level references to check functions (set by HealthCheckServer)
    readiness_check: ClassVar[Callable[[HealthCheckHandler], bool] | None] = None
    status_provider: ClassVar[Callable[[HealthCheckHandler], dict[str, object]] | None] = None

    def do_GET(self) -> None:
        """
        Handle GET requests to health check endpoints.

        Routes:
            /health - Always returns 200 if server is running (liveness)
            /ready  - Returns 200 if readiness_check passes, 503 otherwise
            /status - Returns detailed status JSON from status_provider
            *       - Returns 404 for unknown paths
        """
        if self.path == "/health":
            self._send_json_response(200, {"status": "healthy"})

        elif self.path == "/ready":
            if self.readiness_check is not None:
                try:
                    is_ready = self.readiness_check()
                    if is_ready:
                        self._send_json_response(200, {"status": "ready"})
                    else:
                        self._send_json_response(503, {"status": "not ready"})
                except Exception as e:
                    self._send_json_response(
                        503,
                        {
                            "status": "not ready",
                            "error": str(e),
                        },
                    )
            else:
                # No readiness check configured, assume ready
                self._send_json_response(200, {"status": "ready"})

        elif self.path == "/status":
            status: dict[str, object] = {"status": "running"}
            if self.status_provider is not None:
                try:
                    additional_status = self.status_provider()
                    status.update(additional_status)
                except Exception as e:
                    status["status_error"] = str(e)
            self._send_json_response(200, status)

        else:
            self._send_json_response(404, {"error": "not found"})

    def _send_json_response(
        self,
        status_code: int,
        body: dict[str, object],
    ) -> None:
        """
        Send JSON response with appropriate headers.

        Args:
            status_code: HTTP status code
            body: Dictionary to serialize as JSON response body
        """
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        _ = self.wfile.write(json.dumps(body).encode("utf-8"))

    @override
    def log_message(self, format: str, *args: object) -> None:
        """
        Suppress default HTTP request logging.

        Health check endpoints are called frequently by orchestrators,
        which would create excessive log noise. Logging is suppressed
        to keep logs focused on application events.
        """
        # Suppress default logging to avoid noise from frequent health checks
        pass


class HealthCheckServer:
    """
    Background HTTP server for health check endpoints.

    Runs in a daemon thread so it doesn't prevent graceful shutdown.
    The server is non-blocking and designed for minimal resource usage.

    Attributes:
        port: TCP port to listen on
        server: HTTPServer instance
        thread: Background thread running the server
    """

    @overload
    def __init__(
        self,
        port: int = 8080,
        readiness_check: None = None,
        status_provider: None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        port: int = 8080,
        readiness_check: Callable[[], bool] | None = None,
        status_provider: Callable[[], dict[str, object]] | None = None,
    ) -> None: ...

    def __init__(
        self,
        port: int = 8080,
        readiness_check: object | None = None,
        status_provider: object | None = None,
    ) -> None:
        """
        Initialize health check server.

        Does not start the server; call start() to begin listening.

        Args:
            port: TCP port to listen on (default: 8080)
            readiness_check: Optional function returning True if service is ready
            status_provider: Optional function returning status dictionary

        Example:
            >>> server = HealthCheckServer(
            ...     port=8080,
            ...     readiness_check=lambda: True,
            ...     status_provider=lambda: {"uptime": 100}
            ... )
            >>> server.start()
        """
        self.port: int = port

        if readiness_check is None:
            readiness_cb: Callable[[], bool] | None = None
        elif callable(readiness_check):
            readiness_cb = cast(Callable[[], bool], readiness_check)
        else:
            msg = "readiness_check must be callable when provided"
            raise TypeError(msg)

        if status_provider is None:
            status_cb: Callable[[], dict[str, object]] | None = None
        elif callable(status_provider):
            status_cb = cast(Callable[[], dict[str, object]], status_provider)
        else:
            msg = "status_provider must be callable when provided"
            raise TypeError(msg)

        self._readiness_check: Callable[[], bool] | None = readiness_cb
        self._status_provider: Callable[[], dict[str, object]] | None = status_cb

        # Configure handler class with callbacks
        # Note: These are stored as class attributes for access by handler instances
        # The callables don't have 'self' since they're externally provided functions
        # Assign callbacks for handler instances, wrapping to absorb the bound self
        if readiness_cb is not None:

            def _readiness_wrapper(_: HealthCheckHandler) -> bool:
                return readiness_cb()

            HealthCheckHandler.readiness_check = _readiness_wrapper
        else:
            HealthCheckHandler.readiness_check = None

        if status_cb is not None:

            def _status_wrapper(_: HealthCheckHandler) -> dict[str, object]:
                return status_cb()

            HealthCheckHandler.status_provider = _status_wrapper
        else:
            HealthCheckHandler.status_provider = None

        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """
        Start health check server in background thread.

        Creates an HTTPServer bound to all interfaces (0.0.0.0) on the
        configured port. The server runs in a daemon thread that will
        be terminated when the main process exits.

        Raises:
            OSError: If the port is already in use

        Example:
            >>> server.start()
            >>> # Server is now accepting connections
        """
        try:
            self.server = HTTPServer(("0.0.0.0", self.port), HealthCheckHandler)
        except OSError as e:
            log_with_context(
                logger,
                "error",
                "Failed to start health check server",
                port=self.port,
                error=str(e),
            )
            raise

        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="health-check-server",
            daemon=True,  # Don't prevent shutdown
        )
        self.thread.start()

        log_with_context(
            logger,
            "info",
            "Health check server started",
            port=self.port,
            endpoints=["/health", "/ready", "/status"],
        )

    def stop(self) -> None:
        """
        Stop health check server gracefully.

        Shuts down the HTTP server and waits for the background thread
        to terminate. Safe to call multiple times or if server was
        never started.

        Example:
            >>> server.stop()
        """
        if self.server is not None:
            self.server.shutdown()

        if self.thread is not None:
            self.thread.join(timeout=5.0)
            if self.thread.is_alive():
                log_with_context(
                    logger,
                    "warning",
                    "Health check server thread did not terminate cleanly",
                )

        log_with_context(
            logger,
            "info",
            "Health check server stopped",
        )

    def __enter__(self) -> HealthCheckServer:
        """Context manager entry - starts the server."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - stops the server."""
        self.stop()
