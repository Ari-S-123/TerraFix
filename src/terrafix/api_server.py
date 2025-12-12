"""
HTTP API server for TerraFix load testing and webhook processing.

This module provides an HTTP API server that accepts compliance failures via
webhooks, enabling both load testing and integration with external systems
that can push failures rather than requiring polling.

The server can run in mock mode for load testing, where it simulates the
full remediation pipeline without requiring real external services (Vanta,
GitHub, Bedrock).

Endpoints:
    POST /webhook   - Process a compliance failure
    POST /batch     - Process multiple failures in batch
    GET  /health    - Liveness check
    GET  /ready     - Readiness check
    GET  /status    - Detailed status with metrics
    GET  /metrics   - Prometheus-format metrics

Usage:
    # Production mode (with real services)
    python -m terrafix.api_server

    # Mock mode for load testing
    TERRAFIX_MOCK_MODE=true python -m terrafix.api_server

    # With locust
    locust -f locustfile.py --host=http://localhost:8081
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, override
from urllib.parse import urlparse

from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


@dataclass
class MockProcessingStats:
    """
    Statistics for mock processing mode.

    Tracks request counts, latencies, and error rates for
    load testing analysis.

    Attributes:
        total_requests: Total requests received
        successful_requests: Successfully processed requests
        failed_requests: Failed requests
        total_latency_ms: Sum of all processing latencies
        min_latency_ms: Minimum observed latency
        max_latency_ms: Maximum observed latency
        start_time: When stats collection started
    """

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    start_time: float = field(default_factory=time.time)
    latencies: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(
        self,
        latency_ms: float,
        success: bool,
    ) -> None:
        """
        Record a processed request.

        Args:
            latency_ms: Processing time in milliseconds
            success: Whether the request was successful
        """
        with self._lock:
            self.total_requests += 1
            if success:
                self.successful_requests += 1
            else:
                self.failed_requests += 1

            self.total_latency_ms += latency_ms
            self.min_latency_ms = min(self.min_latency_ms, latency_ms)
            self.max_latency_ms = max(self.max_latency_ms, latency_ms)
            self.latencies.append(latency_ms)

    def to_dict(self) -> dict[str, object]:
        """
        Convert stats to dictionary for JSON serialization.

        Returns:
            Dictionary with all statistics
        """
        with self._lock:
            uptime = time.time() - self.start_time
            avg_latency = (
                self.total_latency_ms / self.total_requests
                if self.total_requests > 0
                else 0.0
            )
            rps = self.total_requests / uptime if uptime > 0 else 0.0

            # Calculate percentiles
            p50, p95, p99 = 0.0, 0.0, 0.0
            if self.latencies:
                sorted_latencies = sorted(self.latencies)
                p50 = sorted_latencies[int(len(sorted_latencies) * 0.50)]
                p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)]
                p99 = sorted_latencies[min(int(len(sorted_latencies) * 0.99), len(sorted_latencies) - 1)]

            return {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate_percent": (
                    self.successful_requests / self.total_requests * 100
                    if self.total_requests > 0
                    else 0.0
                ),
                "uptime_seconds": uptime,
                "requests_per_second": rps,
                "latency_ms": {
                    "avg": avg_latency,
                    "min": self.min_latency_ms if self.total_requests > 0 else 0.0,
                    "max": self.max_latency_ms,
                    "p50": p50,
                    "p95": p95,
                    "p99": p99,
                },
            }

    def reset(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self.total_requests = 0
            self.successful_requests = 0
            self.failed_requests = 0
            self.total_latency_ms = 0.0
            self.min_latency_ms = float("inf")
            self.max_latency_ms = 0.0
            self.start_time = time.time()
            self.latencies = []


# Global stats instance
_stats = MockProcessingStats()

# Global flags for mock mode
_mock_mode = False
_mock_latency_ms = 100.0  # Simulated processing latency
_mock_failure_rate = 0.0  # Probability of simulated failure

# Service state
_is_ready = False
_shutdown_requested = False


class MockProcessor:
    """
    Mock processor that simulates the remediation pipeline.

    Provides configurable latency and failure rates for realistic
    load testing without requiring real external services.

    Attributes:
        latency_ms: Simulated processing time in milliseconds
        failure_rate: Probability of simulated failure (0.0 to 1.0)
    """

    def __init__(
        self,
        latency_ms: float = 100.0,
        failure_rate: float = 0.0,
    ) -> None:
        """
        Initialize mock processor.

        Args:
            latency_ms: Simulated processing latency
            failure_rate: Probability of simulated failure
        """
        self.latency_ms = latency_ms
        self.failure_rate = failure_rate
        import random
        self._random = random.Random()

    def process_failure(self, failure_data: dict[str, object]) -> dict[str, object]:
        """
        Simulate processing a compliance failure.

        Args:
            failure_data: Failure data from webhook

        Returns:
            Processing result with PR URL or error

        Raises:
            Exception: If simulated failure occurs
        """
        # Simulate processing time
        time.sleep(self.latency_ms / 1000)

        # Simulate random failure
        if self._random.random() < self.failure_rate:
            raise RuntimeError("Simulated processing failure")

        # Generate mock PR URL
        test_id = failure_data.get("test_id", "unknown")
        return {
            "success": True,
            "pr_url": f"https://github.com/mock-org/mock-repo/pull/{hash(str(test_id)) % 10000}",
            "failure_hash": f"mock-{hash(str(failure_data))}",
            "message": "Mock processing completed successfully",
        }


# Global mock processor
_mock_processor: MockProcessor | None = None


class APIRequestHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for TerraFix API endpoints.

    Handles webhook processing, health checks, and metrics endpoints.
    Supports both real processing mode and mock mode for load testing.
    """

    # Class-level configuration (set by APIServer)
    real_processor: ClassVar[object | None] = None

    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self._send_json(200, {"status": "healthy"})

        elif path == "/ready":
            if _is_ready:
                self._send_json(200, {"status": "ready"})
            else:
                self._send_json(503, {"status": "not ready"})

        elif path == "/status":
            status = {
                "status": "running",
                "mock_mode": _mock_mode,
                "stats": _stats.to_dict(),
            }
            self._send_json(200, status)

        elif path == "/metrics":
            self._send_metrics()

        elif path == "/stats/reset":
            _stats.reset()
            self._send_json(200, {"message": "Stats reset"})

        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/webhook":
            self._handle_webhook()

        elif path == "/batch":
            self._handle_batch()

        elif path == "/configure":
            self._handle_configure()

        else:
            self._send_json(404, {"error": "Not found"})

    def _handle_webhook(self) -> None:
        """
        Handle single failure webhook.

        Reads failure data from request body, processes it (real or mock),
        and returns the result.
        """
        start_time = time.perf_counter()

        try:
            # Read request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            failure_data = json.loads(body.decode("utf-8"))

            # Process failure
            if _mock_mode and _mock_processor is not None:
                result = _mock_processor.process_failure(failure_data)
            else:
                result = self._process_real(failure_data)

            # Record success
            latency_ms = (time.perf_counter() - start_time) * 1000
            _stats.record_request(latency_ms, True)

            self._send_json(200, result)

        except json.JSONDecodeError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _stats.record_request(latency_ms, False)
            self._send_json(400, {"error": f"Invalid JSON: {e}"})

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            _stats.record_request(latency_ms, False)
            self._send_json(500, {"error": str(e)})

    def _handle_batch(self) -> None:
        """
        Handle batch failure processing.

        Reads array of failures from request body, processes each,
        and returns array of results.
        """
        start_time = time.perf_counter()

        try:
            # Read request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            failures = json.loads(body.decode("utf-8"))

            if not isinstance(failures, list):
                self._send_json(400, {"error": "Expected array of failures"})
                return

            results = []
            for failure_data in failures:
                try:
                    if _mock_mode and _mock_processor is not None:
                        result = _mock_processor.process_failure(failure_data)
                    else:
                        result = self._process_real(failure_data)
                    results.append(result)
                except Exception as e:
                    results.append({
                        "success": False,
                        "error": str(e),
                    })

            # Record stats
            latency_ms = (time.perf_counter() - start_time) * 1000
            successful = sum(1 for r in results if r.get("success", False))
            _stats.record_request(latency_ms, successful == len(results))

            self._send_json(200, {
                "total": len(results),
                "successful": successful,
                "failed": len(results) - successful,
                "results": results,
            })

        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"Invalid JSON: {e}"})

        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_configure(self) -> None:
        """
        Handle runtime configuration updates.

        Allows adjusting mock mode parameters during load testing.
        """
        global _mock_latency_ms, _mock_failure_rate, _mock_processor

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            config = json.loads(body.decode("utf-8"))

            if "latency_ms" in config:
                _mock_latency_ms = float(config["latency_ms"])
            if "failure_rate" in config:
                _mock_failure_rate = float(config["failure_rate"])

            # Update mock processor
            if _mock_mode:
                _mock_processor = MockProcessor(
                    latency_ms=_mock_latency_ms,
                    failure_rate=_mock_failure_rate,
                )

            self._send_json(200, {
                "message": "Configuration updated",
                "latency_ms": _mock_latency_ms,
                "failure_rate": _mock_failure_rate,
            })

        except Exception as e:
            self._send_json(400, {"error": str(e)})

    def _process_real(self, failure_data: dict[str, object]) -> dict[str, object]:
        """
        Process failure using real remediation pipeline.

        Args:
            failure_data: Failure data from webhook

        Returns:
            Processing result

        Raises:
            NotImplementedError: If real processor not configured
        """
        # Import here to avoid circular imports
        from terrafix.vanta_client import Failure

        # Convert dict to Failure object
        current_state_raw = failure_data.get("current_state", {})
        current_state: dict[str, object] = current_state_raw if isinstance(current_state_raw, dict) else {}

        required_state_raw = failure_data.get("required_state", {})
        required_state: dict[str, object] = required_state_raw if isinstance(required_state_raw, dict) else {}

        resource_details_raw = failure_data.get("resource_details")
        resource_details: dict[str, object] = resource_details_raw if isinstance(resource_details_raw, dict) else {}

        failure = Failure(
            test_id=str(failure_data.get("test_id", "")),
            test_name=str(failure_data.get("test_name", "")),
            resource_arn=str(failure_data.get("resource_arn", "")),
            resource_type=str(failure_data.get("resource_type", "")),
            failure_reason=str(failure_data.get("failure_reason", "")),
            severity=str(failure_data.get("severity", "medium")),
            framework=str(failure_data.get("framework", "SOC2")),
            failed_at=str(failure_data.get("failed_at", "")),
            current_state=current_state,
            required_state=required_state,
            resource_id=str(failure_data.get("resource_id", "")),
            resource_details=resource_details,
        )

        if self.real_processor is None:
            raise NotImplementedError(
                "Real processor not configured. Run in mock mode for load testing."
            )

        # Process using real pipeline
        # This is a placeholder - actual implementation would use orchestrator
        return {
            "success": True,
            "message": "Real processing not yet implemented for API mode",
            "test_id": failure.test_id,
        }

    def _send_json(
        self,
        status_code: int,
        body: object,
    ) -> None:
        """Send JSON response."""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        _ = self.wfile.write(json.dumps(body).encode("utf-8"))

    def _send_metrics(self) -> None:
        """Send Prometheus-format metrics."""
        stats = _stats.to_dict()
        latency_stats = stats.get("latency_ms", {})
        if not isinstance(latency_stats, dict):
            latency_stats = {}

        lines = [
            "# HELP terrafix_requests_total Total number of requests",
            "# TYPE terrafix_requests_total counter",
            f'terrafix_requests_total{{status="success"}} {stats.get("successful_requests", 0)}',
            f'terrafix_requests_total{{status="failed"}} {stats.get("failed_requests", 0)}',
            "",
            "# HELP terrafix_request_latency_ms Request latency in milliseconds",
            "# TYPE terrafix_request_latency_ms gauge",
            f'terrafix_request_latency_ms{{quantile="0.5"}} {latency_stats.get("p50", 0)}',
            f'terrafix_request_latency_ms{{quantile="0.95"}} {latency_stats.get("p95", 0)}',
            f'terrafix_request_latency_ms{{quantile="0.99"}} {latency_stats.get("p99", 0)}',
            "",
            "# HELP terrafix_requests_per_second Current request rate",
            "# TYPE terrafix_requests_per_second gauge",
            f"terrafix_requests_per_second {stats.get('requests_per_second', 0):.2f}",
        ]

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        _ = self.wfile.write("\n".join(lines).encode("utf-8"))

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Suppress default HTTP request logging."""
        pass


class APIServer:
    """
    HTTP API server for TerraFix.

    Provides webhook endpoints for processing compliance failures
    and monitoring endpoints for health checks and metrics.

    Attributes:
        port: TCP port to listen on
        mock_mode: Whether to run in mock mode
    """

    def __init__(
        self,
        port: int = 8081,
        mock_mode: bool = False,
        mock_latency_ms: float = 100.0,
        mock_failure_rate: float = 0.0,
    ) -> None:
        """
        Initialize API server.

        Args:
            port: TCP port to listen on
            mock_mode: Enable mock mode for load testing
            mock_latency_ms: Simulated latency in mock mode
            mock_failure_rate: Simulated failure rate in mock mode
        """
        global _mock_mode, _mock_latency_ms, _mock_failure_rate, _mock_processor

        self.port = port
        _mock_mode = mock_mode
        _mock_latency_ms = mock_latency_ms
        _mock_failure_rate = mock_failure_rate

        if mock_mode:
            _mock_processor = MockProcessor(
                latency_ms=mock_latency_ms,
                failure_rate=mock_failure_rate,
            )

        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start API server in background thread."""
        global _is_ready

        try:
            self.server = HTTPServer(("0.0.0.0", self.port), APIRequestHandler)
        except OSError as e:
            log_with_context(
                logger,
                "error",
                "Failed to start API server",
                port=self.port,
                error=str(e),
            )
            raise

        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="api-server",
            daemon=True,
        )
        self.thread.start()
        _is_ready = True

        log_with_context(
            logger,
            "info",
            "API server started",
            port=self.port,
            mock_mode=_mock_mode,
            endpoints=["/webhook", "/batch", "/health", "/ready", "/status", "/metrics"],
        )

    def stop(self) -> None:
        """Stop API server gracefully."""
        global _is_ready, _shutdown_requested

        _is_ready = False
        _shutdown_requested = True

        if self.server is not None:
            self.server.shutdown()

        if self.thread is not None:
            self.thread.join(timeout=5.0)

        log_with_context(
            logger,
            "info",
            "API server stopped",
            final_stats=_stats.to_dict(),
        )

    def run_forever(self) -> None:
        """Run server in foreground (blocking)."""
        global _is_ready

        try:
            self.server = HTTPServer(("0.0.0.0", self.port), APIRequestHandler)
            _is_ready = True

            log_with_context(
                logger,
                "info",
                "API server started (foreground)",
                port=self.port,
                mock_mode=_mock_mode,
            )

            self.server.serve_forever()

        except KeyboardInterrupt:
            log_with_context(
                logger,
                "info",
                "Received interrupt signal",
            )
        finally:
            _is_ready = False
            if self.server is not None:
                self.server.shutdown()

    def __enter__(self) -> APIServer:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type: type, exc_val: Exception, exc_tb: object) -> None:
        """Context manager exit."""
        self.stop()


def main() -> int:
    """
    Main entry point for API server.

    Reads configuration from environment variables:
        TERRAFIX_API_PORT: Port to listen on (default: 8081)
        TERRAFIX_MOCK_MODE: Enable mock mode (default: false)
        TERRAFIX_MOCK_LATENCY_MS: Mock processing latency (default: 100)
        TERRAFIX_MOCK_FAILURE_RATE: Mock failure rate (default: 0.0)

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Configure logging
    from terrafix.logging_config import setup_logging
    setup_logging("INFO")

    # Read configuration from environment
    port = int(os.environ.get("TERRAFIX_API_PORT", "8081"))
    mock_mode = os.environ.get("TERRAFIX_MOCK_MODE", "false").lower() == "true"
    mock_latency_ms = float(os.environ.get("TERRAFIX_MOCK_LATENCY_MS", "100"))
    mock_failure_rate = float(os.environ.get("TERRAFIX_MOCK_FAILURE_RATE", "0.0"))

    log_with_context(
        logger,
        "info",
        "Starting TerraFix API Server",
        port=port,
        mock_mode=mock_mode,
        mock_latency_ms=mock_latency_ms,
        mock_failure_rate=mock_failure_rate,
    )

    server = APIServer(
        port=port,
        mock_mode=mock_mode,
        mock_latency_ms=mock_latency_ms,
        mock_failure_rate=mock_failure_rate,
    )

    try:
        server.run_forever()
    except Exception as e:
        log_with_context(
            logger,
            "error",
            "API server failed",
            error=str(e),
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

