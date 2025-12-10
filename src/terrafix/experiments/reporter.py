"""
Experiment results reporter for TerraFix.

This module provides data structures and utilities for collecting,
summarizing, and exporting experiment results. It supports multiple
output formats including JSON and CSV.

Usage:
    from terrafix.experiments.reporter import ExperimentResult, ExperimentReporter

    result = ExperimentResult(
        experiment_type="throughput",
        profile="steady_state",
        duration_seconds=300,
    )

    # Record metrics during experiment
    result.record_processed(failure_hash="abc123", latency_ms=150.5)

    # Generate report
    reporter = ExperimentReporter(result)
    summary = reporter.generate_summary()
    reporter.export_json("results.json")
"""

import csv
import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class ExperimentResult:
    """
    Container for experiment metrics and results.

    Collects timing data, success/failure counts, and error details
    during an experiment run for later analysis.

    Attributes:
        experiment_type: Type of experiment (throughput, resilience, scalability)
        profile: Workload profile used (steady_state, burst, cascade)
        duration_seconds: Configured experiment duration
        start_time: When the experiment started
        end_time: When the experiment ended
        total_generated: Number of failures generated
        total_processed: Number of failures successfully processed
        total_skipped: Number of failures skipped (duplicates)
        total_failed: Number of failures that errored
        latencies_ms: List of processing latencies in milliseconds
        errors: List of error messages encountered
        stage_timings: Per-stage timing breakdowns
    """

    experiment_type: str
    profile: str
    duration_seconds: int
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    total_generated: int = 0
    total_processed: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stage_timings: dict[str, list[float]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_generated(self) -> None:
        """Record that a failure was generated."""
        self.total_generated += 1

    def record_processed(self, failure_hash: str, latency_ms: float) -> None:
        """
        Record successful processing of a failure.

        Args:
            failure_hash: Hash of the processed failure
            latency_ms: Processing time in milliseconds
        """
        self.total_processed += 1
        self.latencies_ms.append(latency_ms)

    def record_skipped(self, failure_hash: str) -> None:
        """
        Record that a failure was skipped (duplicate).

        Args:
            failure_hash: Hash of the skipped failure
        """
        self.total_skipped += 1

    def record_failed(self, failure_hash: str, error: str) -> None:
        """
        Record that processing a failure resulted in an error.

        Args:
            failure_hash: Hash of the failed failure
            error: Error message
        """
        self.total_failed += 1
        self.errors.append(error)

    def record_stage_timing(self, stage: str, duration_ms: float) -> None:
        """
        Record timing for a specific processing stage.

        Args:
            stage: Name of the processing stage
            duration_ms: Duration in milliseconds
        """
        if stage not in self.stage_timings:
            self.stage_timings[stage] = []
        self.stage_timings[stage].append(duration_ms)

    def finish(self) -> None:
        """Mark the experiment as finished."""
        self.end_time = datetime.now(UTC)

    @property
    def actual_duration_seconds(self) -> float:
        """Calculate actual experiment duration."""
        if self.end_time is None:
            return (datetime.now(UTC) - self.start_time).total_seconds()
        return (self.end_time - self.start_time).total_seconds()

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        total = self.total_processed + self.total_failed
        if total == 0:
            return 0.0
        return (self.total_processed / total) * 100

    @property
    def throughput_per_second(self) -> float:
        """Calculate average throughput in failures per second."""
        duration = self.actual_duration_seconds
        if duration == 0:
            return 0.0
        return self.total_processed / duration


class ExperimentReporter:
    """
    Reporter for generating experiment summaries and exports.

    Takes experiment results and produces human-readable summaries
    and machine-readable exports in various formats.

    Attributes:
        result: The experiment result to report on

    Example:
        >>> reporter = ExperimentReporter(result)
        >>> print(reporter.generate_summary())
        >>> reporter.export_json("results.json")
    """

    def __init__(self, result: ExperimentResult) -> None:
        """
        Initialize the reporter.

        Args:
            result: Experiment result to report on
        """
        self.result = result

    def generate_summary(self) -> str:
        """
        Generate a human-readable summary of the experiment.

        Returns:
            Formatted string summary
        """
        r = self.result

        # Calculate latency statistics
        latency_stats = self._calculate_latency_stats()

        lines = [
            "=" * 60,
            f"TerraFix Experiment Report",
            "=" * 60,
            "",
            f"Experiment Type: {r.experiment_type}",
            f"Workload Profile: {r.profile}",
            f"Start Time: {r.start_time.isoformat()}",
            f"End Time: {r.end_time.isoformat() if r.end_time else 'In Progress'}",
            f"Duration: {r.actual_duration_seconds:.1f}s (configured: {r.duration_seconds}s)",
            "",
            "-" * 40,
            "Processing Summary",
            "-" * 40,
            f"Total Generated: {r.total_generated}",
            f"Total Processed: {r.total_processed}",
            f"Total Skipped: {r.total_skipped}",
            f"Total Failed: {r.total_failed}",
            f"Success Rate: {r.success_rate:.1f}%",
            f"Throughput: {r.throughput_per_second:.2f} failures/second",
            "",
        ]

        if latency_stats:
            lines.extend([
                "-" * 40,
                "Latency Statistics (ms)",
                "-" * 40,
                f"Min: {latency_stats['min']:.1f}",
                f"Max: {latency_stats['max']:.1f}",
                f"Mean: {latency_stats['mean']:.1f}",
                f"Median: {latency_stats['median']:.1f}",
                f"P95: {latency_stats['p95']:.1f}",
                f"P99: {latency_stats['p99']:.1f}",
                "",
            ])

        if r.stage_timings:
            lines.extend([
                "-" * 40,
                "Stage Timing Breakdown (ms avg)",
                "-" * 40,
            ])
            for stage, timings in r.stage_timings.items():
                if timings:
                    avg = statistics.mean(timings)
                    lines.append(f"{stage}: {avg:.1f}")
            lines.append("")

        if r.errors:
            lines.extend([
                "-" * 40,
                f"Errors ({len(r.errors)} total)",
                "-" * 40,
            ])
            # Show first 5 unique errors
            unique_errors = list(set(r.errors))[:5]
            for error in unique_errors:
                lines.append(f"  - {error[:80]}...")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)

    def _calculate_latency_stats(self) -> dict[str, float] | None:
        """
        Calculate latency percentiles and statistics.

        Returns:
            Dictionary of statistics or None if no data
        """
        latencies = self.result.latencies_ms
        if not latencies:
            return None

        sorted_latencies = sorted(latencies)
        return {
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "p95": self._percentile(sorted_latencies, 95),
            "p99": self._percentile(sorted_latencies, 99),
        }

    def _percentile(self, sorted_values: list[float], percentile: int) -> float:
        """Calculate percentile from sorted values."""
        if not sorted_values:
            return 0.0
        index = int(len(sorted_values) * percentile / 100)
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]

    def to_dict(self) -> dict[str, Any]:
        """
        Convert result to dictionary for serialization.

        Returns:
            Dictionary representation of results
        """
        r = self.result
        latency_stats = self._calculate_latency_stats()

        return {
            "experiment_type": r.experiment_type,
            "profile": r.profile,
            "duration": {
                "configured_seconds": r.duration_seconds,
                "actual_seconds": r.actual_duration_seconds,
            },
            "timestamps": {
                "start": r.start_time.isoformat(),
                "end": r.end_time.isoformat() if r.end_time else None,
            },
            "counts": {
                "generated": r.total_generated,
                "processed": r.total_processed,
                "skipped": r.total_skipped,
                "failed": r.total_failed,
            },
            "rates": {
                "success_rate_percent": r.success_rate,
                "throughput_per_second": r.throughput_per_second,
            },
            "latency_ms": latency_stats,
            "stage_timings_ms": {
                stage: {
                    "mean": statistics.mean(timings) if timings else 0,
                    "p95": self._percentile(sorted(timings), 95) if timings else 0,
                }
                for stage, timings in r.stage_timings.items()
            },
            "errors": {
                "count": len(r.errors),
                "samples": list(set(r.errors))[:10],
            },
            "metadata": r.metadata,
        }

    def export_json(self, path: str | Path) -> None:
        """
        Export results to JSON file.

        Args:
            path: Output file path
        """
        path = Path(path)
        with path.open("w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def export_csv(self, path: str | Path) -> None:
        """
        Export results to CSV file.

        Creates a single-row CSV with all key metrics.

        Args:
            path: Output file path
        """
        path = Path(path)
        r = self.result
        latency_stats = self._calculate_latency_stats() or {}

        row = {
            "experiment_type": r.experiment_type,
            "profile": r.profile,
            "duration_configured_s": r.duration_seconds,
            "duration_actual_s": r.actual_duration_seconds,
            "start_time": r.start_time.isoformat(),
            "end_time": r.end_time.isoformat() if r.end_time else "",
            "total_generated": r.total_generated,
            "total_processed": r.total_processed,
            "total_skipped": r.total_skipped,
            "total_failed": r.total_failed,
            "success_rate_percent": r.success_rate,
            "throughput_per_second": r.throughput_per_second,
            "latency_min_ms": latency_stats.get("min", ""),
            "latency_max_ms": latency_stats.get("max", ""),
            "latency_mean_ms": latency_stats.get("mean", ""),
            "latency_median_ms": latency_stats.get("median", ""),
            "latency_p95_ms": latency_stats.get("p95", ""),
            "latency_p99_ms": latency_stats.get("p99", ""),
            "error_count": len(r.errors),
        }

        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            writer.writeheader()
            writer.writerow(row)

