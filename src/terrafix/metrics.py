"""
Metrics collection system for TerraFix observability.

This module provides a centralized metrics collector for tracking counters,
gauges, and timers across the TerraFix pipeline. Metrics are exposed via
a JSON endpoint for monitoring and alerting.

The collector is thread-safe and uses a singleton pattern to ensure
consistent metrics across all components.

Usage:
    from terrafix.metrics import metrics_collector, StageTimer

    # Increment counters
    metrics_collector.increment("failures_processed_total")
    metrics_collector.increment("api_errors_total", labels={"service": "bedrock"})

    # Set gauges
    metrics_collector.set_gauge("queue_depth", 5)
    metrics_collector.set_gauge("active_workers", 3)

    # Time operations
    with metrics_collector.start_timer(StageTimer.BEDROCK_INFERENCE):
        # ... do work ...
        pass

    # Get all metrics as JSON
    metrics = metrics_collector.get_metrics()
"""

from __future__ import annotations

import statistics
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from enum import Enum
from types import TracebackType
from typing import Any


class StageTimer(str, Enum):
    """
    Named stages in the processing pipeline for timing.

    These constants identify the major stages in failure processing
    to enable per-stage latency analysis.

    Attributes:
        FETCH_VANTA: Time to fetch failures from Vanta API
        CLONE_REPO: Time to clone Git repository
        PARSE_TERRAFORM: Time to parse Terraform files
        BEDROCK_INFERENCE: Time for Claude inference via Bedrock
        VALIDATE_FIX: Time to validate generated Terraform fix
        CREATE_PR: Time to create GitHub PR
        TOTAL_PROCESSING: End-to-end processing time for one failure
    """

    FETCH_VANTA = "fetch_vanta"
    CLONE_REPO = "clone_repo"
    PARSE_TERRAFORM = "parse_terraform"
    BEDROCK_INFERENCE = "bedrock_inference"
    VALIDATE_FIX = "validate_fix"
    CREATE_PR = "create_pr"
    TOTAL_PROCESSING = "total_processing"


class Timer:
    """
    Context manager for timing operations.

    Tracks start and end times, automatically recording duration
    to the metrics collector when the context exits.

    Attributes:
        name: Name of the timer (usually a StageTimer value)
        start_time: Unix timestamp when timer started
        collector: Reference to MetricsCollector for recording

    Example:
        >>> with metrics_collector.start_timer("my_operation") as timer:
        ...     # do work
        ...     pass
        >>> print(f"Took {timer.duration}s")
    """

    def __init__(
        self,
        name: str,
        collector: MetricsCollector,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize timer.

        Args:
            name: Name of the operation being timed
            collector: MetricsCollector instance for recording
            labels: Optional labels for the timer metric
        """
        self.name: str = name
        self.collector: MetricsCollector = collector
        self.labels: dict[str, str] = labels or {}
        self.start_time: float = 0.0
        self.duration: float = 0.0

    def __enter__(self) -> Timer:
        """Start the timer."""
        self.start_time = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Stop the timer and record duration."""
        self.stop()

    def stop(self) -> float:
        """
        Stop the timer and record duration.

        Returns:
            Duration in seconds
        """
        self.duration = time.perf_counter() - self.start_time
        self.collector._record_timing(self.name, self.duration, self.labels)
        return self.duration


class MetricsCollector:
    """
    Thread-safe metrics collector for TerraFix observability.

    Collects three types of metrics:
    - Counters: Monotonically increasing values (e.g., total failures processed)
    - Gauges: Point-in-time values (e.g., current queue depth)
    - Histograms: Duration distributions (e.g., processing latency percentiles)

    The collector uses a singleton pattern to ensure all components
    share the same metrics state.

    Attributes:
        _counters: Counter values keyed by (name, labels_tuple)
        _gauges: Gauge values keyed by (name, labels_tuple)
        _timings: List of timing values keyed by (name, labels_tuple)
        _lock: Threading lock for thread-safe access
        _start_time: When the collector was initialized
    """

    _instance: MetricsCollector | None = None
    _lock_class: threading.Lock = threading.Lock()

    def __new__(cls) -> MetricsCollector:
        """Singleton pattern implementation."""
        with cls._lock_class:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        """Initialize the metrics collector."""
        # Avoid re-initialization in singleton
        if getattr(self, "_initialized", False):
            return

        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._timings: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(
            list
        )
        self._lock: threading.Lock = threading.Lock()
        self._start_time: datetime = datetime.now(UTC)
        self._initialized: bool = True

    def _labels_to_tuple(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        """
        Convert labels dict to hashable tuple.

        Args:
            labels: Labels dictionary or None

        Returns:
            Sorted tuple of (key, value) pairs
        """
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    def increment(
        self,
        name: str,
        value: int = 1,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Increment a counter metric.

        Counters are monotonically increasing values used for totals
        like processed failures, errors, or PRs created.

        Args:
            name: Counter name (e.g., "failures_processed_total")
            value: Amount to increment (default: 1)
            labels: Optional labels (e.g., {"service": "vanta"})

        Example:
            >>> metrics_collector.increment("api_errors_total", labels={"service": "bedrock"})
        """
        key = (name, self._labels_to_tuple(labels))
        with self._lock:
            self._counters[key] += value

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Set a gauge metric to a specific value.

        Gauges are point-in-time values that can go up or down,
        used for things like queue depth or active workers.

        Args:
            name: Gauge name (e.g., "queue_depth")
            value: Current value
            labels: Optional labels

        Example:
            >>> metrics_collector.set_gauge("active_workers", 3)
        """
        key = (name, self._labels_to_tuple(labels))
        with self._lock:
            self._gauges[key] = value

    def start_timer(
        self,
        name: str | StageTimer,
        labels: dict[str, str] | None = None,
    ) -> Timer:
        """
        Start a timer for measuring operation duration.

        Returns a context manager that automatically records
        duration when the context exits.

        Args:
            name: Timer name (usually a StageTimer value)
            labels: Optional labels

        Returns:
            Timer context manager

        Example:
            >>> with metrics_collector.start_timer(StageTimer.BEDROCK_INFERENCE):
            ...     response = bedrock.invoke_model(...)
        """
        timer_name = name.value if isinstance(name, StageTimer) else name
        return Timer(timer_name, self, labels)

    def _record_timing(
        self,
        name: str,
        duration: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Record a timing value.

        Called automatically by Timer.stop().

        Args:
            name: Timer name
            duration: Duration in seconds
            labels: Optional labels
        """
        key = (name, self._labels_to_tuple(labels))
        with self._lock:
            self._timings[key].append(duration)
            # Keep only last 1000 timings to prevent memory growth
            if len(self._timings[key]) > 1000:
                self._timings[key] = self._timings[key][-1000:]

    def get_counter(
        self,
        name: str,
        labels: dict[str, str] | None = None,
    ) -> int:
        """
        Get current value of a counter.

        Args:
            name: Counter name
            labels: Optional labels

        Returns:
            Current counter value (0 if not set)
        """
        key = (name, self._labels_to_tuple(labels))
        with self._lock:
            return self._counters.get(key, 0)

    def get_gauge(
        self,
        name: str,
        labels: dict[str, str] | None = None,
    ) -> float | None:
        """
        Get current value of a gauge.

        Args:
            name: Gauge name
            labels: Optional labels

        Returns:
            Current gauge value or None if not set
        """
        key = (name, self._labels_to_tuple(labels))
        with self._lock:
            return self._gauges.get(key)

    def get_timing_stats(
        self,
        name: str,
        labels: dict[str, str] | None = None,
    ) -> dict[str, float] | None:
        """
        Get timing statistics for a named timer.

        Args:
            name: Timer name
            labels: Optional labels

        Returns:
            Dictionary with count, min, max, mean, p50, p95, p99
            or None if no timings recorded
        """
        key = (name, self._labels_to_tuple(labels))
        with self._lock:
            timings = self._timings.get(key, [])
            if not timings:
                return None

            sorted_timings = sorted(timings)
            return {
                "count": len(timings),
                "min": min(timings),
                "max": max(timings),
                "mean": statistics.mean(timings),
                "p50": self._percentile(sorted_timings, 50),
                "p95": self._percentile(sorted_timings, 95),
                "p99": self._percentile(sorted_timings, 99),
            }

    def _percentile(self, sorted_values: list[float], percentile: int) -> float:
        """
        Calculate percentile from sorted values.

        Args:
            sorted_values: Pre-sorted list of values
            percentile: Percentile to calculate (0-100)

        Returns:
            Value at the given percentile
        """
        if not sorted_values:
            return 0.0
        index = int(len(sorted_values) * percentile / 100)
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]

    def get_metrics(self) -> dict[str, Any]:
        """
        Get all metrics as a JSON-serializable dictionary.

        Returns:
            Dictionary containing:
            - timestamp: Current UTC timestamp
            - uptime_seconds: Time since collector started
            - counters: All counter values
            - gauges: All gauge values
            - timings: Timing statistics for all timers

        Example:
            >>> metrics = metrics_collector.get_metrics()
            >>> print(json.dumps(metrics, indent=2))
        """
        now = datetime.now(UTC)
        uptime = (now - self._start_time).total_seconds()

        with self._lock:
            # Format counters
            counters: dict[str, Any] = {}
            for (name, labels_tuple), value in self._counters.items():
                if labels_tuple:
                    labels_dict = dict(labels_tuple)
                    label_str = ",".join(f"{k}={v}" for k, v in labels_dict.items())
                    counters[f"{name}{{{label_str}}}"] = value
                else:
                    counters[name] = value

            # Format gauges
            gauges: dict[str, float] = {}
            for (name, labels_tuple), gauge_value in self._gauges.items():
                if labels_tuple:
                    labels_dict = dict(labels_tuple)
                    label_str = ",".join(f"{k}={v}" for k, v in labels_dict.items())
                    gauges[f"{name}{{{label_str}}}"] = gauge_value
                else:
                    gauges[name] = gauge_value

            # Format timings
            timings: dict[str, Any] = {}
            for (name, labels_tuple), values in self._timings.items():
                if not values:
                    continue

                sorted_values = sorted(values)
                stats = {
                    "count": len(values),
                    "min_seconds": min(values),
                    "max_seconds": max(values),
                    "mean_seconds": statistics.mean(values),
                    "p50_seconds": self._percentile(sorted_values, 50),
                    "p95_seconds": self._percentile(sorted_values, 95),
                    "p99_seconds": self._percentile(sorted_values, 99),
                }

                if labels_tuple:
                    labels_dict = dict(labels_tuple)
                    label_str = ",".join(f"{k}={v}" for k, v in labels_dict.items())
                    timings[f"{name}{{{label_str}}}"] = stats
                else:
                    timings[name] = stats

        return {
            "timestamp": now.isoformat(),
            "uptime_seconds": uptime,
            "counters": counters,
            "gauges": gauges,
            "timings": timings,
        }

    def reset(self) -> None:
        """
        Reset all metrics to initial state.

        Useful for testing or when restarting metric collection.
        """
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._timings.clear()
            self._start_time = datetime.now(UTC)


# Global singleton instance for convenience
metrics_collector = MetricsCollector()


# Predefined counter names for consistency
class MetricNames:
    """
    Standard metric names used throughout TerraFix.

    Using constants ensures consistency and enables IDE autocomplete.
    """

    # Counters
    FAILURES_PROCESSED_TOTAL = "failures_processed_total"
    FAILURES_SUCCESSFUL_TOTAL = "failures_successful_total"
    FAILURES_SKIPPED_TOTAL = "failures_skipped_total"
    FAILURES_FAILED_TOTAL = "failures_failed_total"
    PRS_CREATED_TOTAL = "prs_created_total"
    API_ERRORS_TOTAL = "api_errors_total"
    RETRIES_TOTAL = "retries_total"

    # Gauges
    QUEUE_DEPTH = "queue_depth"
    ACTIVE_WORKERS = "active_workers"
    LAST_POLL_TIMESTAMP = "last_poll_timestamp"

    # Timings are handled by StageTimer enum
