"""
Long-running service for TerraFix compliance remediation.

This module implements the main service loop that polls Vanta for failures,
dispatches them to the orchestrator for processing, and handles graceful
shutdown on SIGTERM/SIGINT.

The service runs continuously until interrupted, polling Vanta at the
configured interval and processing failures concurrently.

Usage:
    python -m terrafix.service
"""

import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from types import FrameType

from terrafix.config import Settings, get_settings
from terrafix.github_pr_creator import GitHubPRCreator
from terrafix.health_check import HealthCheckServer
from terrafix.logging_config import get_logger, log_with_context, setup_logging
from terrafix.orchestrator import ProcessingResult, process_failure
from terrafix.redis_state_store import RedisStateStore
from terrafix.remediation_generator import TerraformRemediationGenerator
from terrafix.vanta_client import Failure, VantaClient

logger = get_logger(__name__)

# Global flag for graceful shutdown
_shutdown_requested = False

# Global service state for health checks
_service_ready = False
_service_start_time: datetime | None = None
_failures_processed = 0
_error_count = 0


def signal_handler(
    signum: int,
    frame: FrameType | None,
) -> None:
    _ = frame  # Signal handler receives frame but we don't use it
    """
    Handle shutdown signals (SIGTERM, SIGINT).

    Sets global flag to request graceful shutdown. The service loop
    will complete current processing and exit cleanly.

    Args:
        signum: Signal number
        frame: Current stack frame
    """
    global _shutdown_requested, _service_ready

    log_with_context(
        logger,
        "info",
        "Shutdown signal received",
        signal=signum,
    )

    _shutdown_requested = True
    _service_ready = False


def _is_service_ready() -> bool:
    """
    Check if service is ready to process failures.

    Used by the health check server for readiness probes.

    Returns:
        True if service is initialized and not shutting down
    """
    return _service_ready and not _shutdown_requested


def _get_service_status() -> dict[str, object]:
    """
    Get detailed service status for health check endpoint.

    Returns:
        Dictionary with service statistics
    """
    uptime_seconds = 0.0
    if _service_start_time is not None:
        uptime_seconds = (datetime.now(UTC) - _service_start_time).total_seconds()

    return {
        "uptime_seconds": uptime_seconds,
        "failures_processed": _failures_processed,
        "errors": _error_count,
        "shutting_down": _shutdown_requested,
    }


def main() -> int:
    """
    Main service entry point.

    Initializes all clients, sets up signal handlers, starts the health
    check server, and runs the main polling loop until shutdown is requested.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    global _service_ready, _service_start_time

    # Load configuration
    try:
        settings = get_settings()
    except Exception as e:
        print(f"Failed to load configuration: {e}", file=sys.stderr)
        return 1

    # Setup logging
    setup_logging(settings.log_level)

    log_with_context(
        logger,
        "info",
        "Starting TerraFix service",
        version="0.1.0",
        poll_interval=settings.poll_interval_seconds,
        max_workers=settings.max_concurrent_workers,
    )

    # Register signal handlers for graceful shutdown
    _ = signal.signal(signal.SIGTERM, signal_handler)
    _ = signal.signal(signal.SIGINT, signal_handler)

    # Start health check server
    health_server = HealthCheckServer(
        port=8080,
        readiness_check=_is_service_ready,
        status_provider=_get_service_status,
    )

    try:
        health_server.start()
    except Exception as e:
        log_with_context(
            logger,
            "error",
            "Failed to start health check server",
            error=str(e),
        )
        return 1

    # Initialize clients
    try:
        vanta = VantaClient(
            api_token=settings.vanta_api_token,
            base_url=settings.vanta_base_url,
        )

        generator = TerraformRemediationGenerator(
            model_id=settings.bedrock_model_id,
            region=settings.aws_region,
        )

        gh = GitHubPRCreator(github_token=settings.github_token)

        state_store = RedisStateStore(
            redis_url=settings.redis_url,
            ttl_days=settings.state_retention_days,
        )

        log_with_context(
            logger,
            "info",
            "Initialized all clients",
        )

        # Mark service as ready for health checks
        _service_ready = True
        _service_start_time = datetime.now(UTC)

    except Exception as e:
        log_with_context(
            logger,
            "error",
            "Failed to initialize clients",
            error=str(e),
        )
        health_server.stop()
        return 1

    # Run main service loop
    try:
        run_service_loop(
            settings=settings,
            vanta=vanta,
            generator=generator,
            gh=gh,
            state_store=state_store,
        )

    except Exception as e:
        log_with_context(
            logger,
            "error",
            "Service loop failed",
            error=str(e),
        )
        return 1

    finally:
        # Cleanup
        _service_ready = False
        health_server.stop()
        state_store.close()

        log_with_context(
            logger,
            "info",
            "TerraFix service stopped",
        )

    return 0


def run_service_loop(
    settings: Settings,
    vanta: VantaClient,
    generator: TerraformRemediationGenerator,
    gh: GitHubPRCreator,
    state_store: RedisStateStore,
) -> None:
    """
    Run the main service polling loop.

    Polls Vanta for failures, processes them concurrently, and sleeps
    between polling cycles. Continues until shutdown is requested.

    Args:
        settings: Application settings
        vanta: Vanta API client
        generator: Bedrock remediation generator
        gh: GitHub PR creator
        state_store: SQLite state store
    """
    last_check = datetime.now(UTC) - timedelta(hours=1)
    cleanup_counter = 0

    log_with_context(
        logger,
        "info",
        "Service loop started",
        last_check=last_check.isoformat(),
    )

    while not _shutdown_requested:
        cycle_start = time.time()

        log_with_context(
            logger,
            "info",
            "Starting polling cycle",
            last_check=last_check.isoformat(),
        )

        try:
            # Fetch failures from Vanta
            failures = vanta.get_failing_tests_since(last_check)

            log_with_context(
                logger,
                "info",
                "Fetched failures from Vanta",
                count=len(failures),
            )

            if failures:
                # Process failures concurrently
                results = process_failures_concurrent(
                    failures=failures,
                    settings=settings,
                    vanta=vanta,
                    generator=generator,
                    gh=gh,
                    state_store=state_store,
                    max_workers=int(settings.max_concurrent_workers),
                )

                # Log summary and update global counters
                successful = sum(1 for r in results if r.success and not r.skipped)
                skipped = sum(1 for r in results if r.skipped)
                failed = sum(1 for r in results if not r.success)

                # Update global counters for health check status
                global _failures_processed, _error_count
                _failures_processed += successful
                _error_count += failed

                log_with_context(
                    logger,
                    "info",
                    "Completed processing cycle",
                    total=len(results),
                    successful=successful,
                    skipped=skipped,
                    failed=failed,
                )

            # Update last_check to current time
            last_check = datetime.now(UTC)

                # Periodic statistics logging (every 10 cycles)
            # Note: Redis handles TTL-based expiration automatically
            cleanup_counter += 1
            if cleanup_counter >= 10:
                cleanup_counter = 0

                # Log statistics
                try:
                    stats = state_store.get_statistics()
                    log_with_context(
                        logger,
                        "info",
                        "State store statistics",
                        stats=stats,
                    )
                except Exception as e:
                    log_with_context(
                        logger,
                        "warning",
                        "Failed to get statistics",
                        error=str(e),
                    )

        except Exception as e:
            log_with_context(
                logger,
                "error",
                "Error in polling cycle",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Continue to next cycle after error

        # Calculate sleep time
        cycle_duration = time.time() - cycle_start
        sleep_time = max(0.0, float(settings.poll_interval_seconds) - cycle_duration)

        if not _shutdown_requested and sleep_time > 0:
            log_with_context(
                logger,
                "info",
                "Sleeping until next cycle",
                sleep_seconds=sleep_time,
                next_cycle_at=(datetime.now(UTC) + timedelta(seconds=sleep_time)).isoformat(),
            )

            # Sleep in small increments to respond quickly to shutdown
            for _ in range(int(sleep_time)):
                if _shutdown_requested:
                    break
                time.sleep(1)

    log_with_context(
        logger,
        "info",
        "Service loop exiting gracefully",
    )


def process_failures_concurrent(
    failures: list[Failure],
    settings: Settings,
    vanta: VantaClient,
    generator: TerraformRemediationGenerator,
    gh: GitHubPRCreator,
    state_store: RedisStateStore,
    max_workers: int = 3,
) -> list[ProcessingResult]:
    """
    Process multiple failures concurrently.

    Uses a thread pool to process failures in parallel while respecting
    the max_workers limit. Returns results for all failures.

    Args:
        failures: List of failures to process
        settings: Application settings
        vanta: Vanta client
        generator: Bedrock generator
        gh: GitHub PR creator
        state_store: State store
        max_workers: Maximum concurrent workers

    Returns:
        List of ProcessingResult for each failure
    """
    results: list[ProcessingResult] = []

    if not failures:
        return results

    log_with_context(
        logger,
        "info",
        "Processing failures concurrently",
        count=len(failures),
        max_workers=max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all failures for processing
        future_to_failure = {
            executor.submit(
                process_failure,
                failure=failure,
                config=settings,
                state_store=state_store,
                vanta=vanta,
                generator=generator,
                gh=gh,
            ): failure
            for failure in failures
        }

        # Collect results as they complete
        for future in as_completed(future_to_failure):
            failure = future_to_failure[future]
            try:
                result = future.result()
                results.append(result)

                if result.success and not result.skipped:
                    log_with_context(
                        logger,
                        "info",
                        "Successfully processed failure",
                        test_id=failure.test_id,
                        pr_url=result.pr_url,
                    )
                elif result.skipped:
                    log_with_context(
                        logger,
                        "info",
                        "Skipped duplicate failure",
                        test_id=failure.test_id,
                    )
                else:
                    log_with_context(
                        logger,
                        "error",
                        "Failed to process failure",
                        test_id=failure.test_id,
                        error=result.error,
                    )

            except Exception as e:
                log_with_context(
                    logger,
                    "error",
                    "Unexpected error processing failure",
                    test_id=failure.test_id,
                    error=str(e),
                )

                # Create error result
                failure_hash = vanta.generate_failure_hash(failure)
                results.append(
                    ProcessingResult(
                        success=False,
                        failure_hash=failure_hash,
                        error=str(e),
                    )
                )

    return results


if __name__ == "__main__":
    sys.exit(main())

