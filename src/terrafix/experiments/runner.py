"""
Experiment runner for TerraFix testing harness.

This module orchestrates experiment execution, coordinating
the synthetic failure generator, failure injector, and result
reporter to run complete experiments.

Supported experiment types:
    - Throughput: Measure processing capacity under load
    - Resilience: Test error handling and recovery
    - Scalability: Test performance with varying repo sizes

Usage:
    from terrafix.experiments.runner import ExperimentRunner
    from terrafix.experiments.profiles import ProfileConfig, WorkloadProfile

    runner = ExperimentRunner()
    config = ProfileConfig(profile=WorkloadProfile.STEADY_STATE)

    result = await runner.run_throughput_experiment(config)
    print(f"Throughput: {result.throughput_per_second:.2f}/s")
"""

import asyncio
import logging
import time
from typing import Any

from terrafix.metrics import metrics_collector

from .generator import SyntheticFailureGenerator
from .injector import FailureInjector
from .profiles import ProfileConfig, WorkloadProfile
from .reporter import ExperimentReporter, ExperimentResult

logger = logging.getLogger(__name__)


class ExperimentRunner:
    """
    Orchestrator for running TerraFix experiments.

    Coordinates synthetic failure generation, optional failure injection,
    and result collection to execute various experiment types.

    Attributes:
        generator: Synthetic failure generator
        injector: Optional failure injector for resilience tests

    Example:
        >>> runner = ExperimentRunner()
        >>> config = ProfileConfig(profile=WorkloadProfile.BURST)
        >>> result = await runner.run_throughput_experiment(config)
    """

    def __init__(
        self,
        seed: int | None = None,
        failure_rate: float = 0.0,
    ) -> None:
        """
        Initialize the experiment runner.

        Args:
            seed: Random seed for reproducible experiments
            failure_rate: Failure injection rate (0.0 to 1.0)
        """
        self.generator = SyntheticFailureGenerator(seed=seed)
        self.injector = FailureInjector(failure_rate=failure_rate, seed=seed)
        self._mock_process_delay_ms = 100  # Simulated processing time

    async def run_throughput_experiment(
        self,
        config: ProfileConfig,
        process_callback: Any | None = None,
    ) -> ExperimentResult:
        """
        Run a throughput experiment.

        Measures how many failures can be processed per unit time
        under the given workload profile.

        Args:
            config: Profile configuration for the experiment
            process_callback: Optional async callback to process failures
                If None, uses mock processing

        Returns:
            ExperimentResult with throughput metrics
        """
        result = ExperimentResult(
            experiment_type="throughput",
            profile=config.profile.value,
            duration_seconds=config.duration_seconds,
            metadata={"repo_size": config.repo_size},
        )

        logger.info(
            "Starting throughput experiment",
            extra={
                "profile": config.profile.value,
                "duration": config.duration_seconds,
            },
        )

        # Reset metrics collector for clean measurement
        metrics_collector.reset()

        try:
            async for failure in self.generator.generate_stream(config):
                result.record_generated()

                start_time = time.perf_counter()

                try:
                    if process_callback:
                        await process_callback(failure)
                    else:
                        # Mock processing
                        await self._mock_process(failure)

                    duration_ms = (time.perf_counter() - start_time) * 1000
                    result.record_processed(failure.test_id, duration_ms)

                except Exception as e:
                    result.record_failed(failure.test_id, str(e))
                    logger.debug(f"Failed to process failure: {e}")

        except asyncio.CancelledError:
            logger.info("Experiment cancelled")
        finally:
            result.finish()

        logger.info(
            "Throughput experiment completed",
            extra={
                "processed": result.total_processed,
                "throughput": result.throughput_per_second,
            },
        )

        return result

    async def run_resilience_experiment(
        self,
        config: ProfileConfig,
        failure_rate: float = 0.2,
        process_callback: Any | None = None,
    ) -> ExperimentResult:
        """
        Run a resilience experiment.

        Tests the system's ability to handle and recover from
        injected failures at the specified rate.

        Args:
            config: Profile configuration for the experiment
            failure_rate: Rate of failure injection (0.0 to 1.0)
            process_callback: Optional async callback to process failures

        Returns:
            ExperimentResult with resilience metrics
        """
        result = ExperimentResult(
            experiment_type="resilience",
            profile=config.profile.value,
            duration_seconds=config.duration_seconds,
            metadata={"failure_rate": failure_rate},
        )

        # Configure injector with specified failure rate
        self.injector = FailureInjector(failure_rate=failure_rate)

        logger.info(
            "Starting resilience experiment",
            extra={
                "profile": config.profile.value,
                "failure_rate": failure_rate,
            },
        )

        metrics_collector.reset()

        try:
            with self.injector.inject_all_failures():
                async for failure in self.generator.generate_stream(config):
                    result.record_generated()

                    start_time = time.perf_counter()

                    try:
                        if process_callback:
                            await process_callback(failure)
                        else:
                            await self._mock_process_with_retries(failure)

                        duration_ms = (time.perf_counter() - start_time) * 1000
                        result.record_processed(failure.test_id, duration_ms)

                    except Exception as e:
                        result.record_failed(failure.test_id, str(e))

        except asyncio.CancelledError:
            logger.info("Experiment cancelled")
        finally:
            result.finish()
            result.metadata["injector_stats"] = self.injector.get_stats()

        logger.info(
            "Resilience experiment completed",
            extra={
                "processed": result.total_processed,
                "failed": result.total_failed,
                "success_rate": result.success_rate,
            },
        )

        return result

    async def run_scalability_experiment(
        self,
        repo_sizes: list[str] | None = None,
        base_config: ProfileConfig | None = None,
    ) -> list[ExperimentResult]:
        """
        Run scalability experiments across different repo sizes.

        Tests performance with varying repository sizes to
        identify scaling characteristics.

        Args:
            repo_sizes: List of repo sizes to test (default: small, medium, large)
            base_config: Base configuration to use for all sizes

        Returns:
            List of ExperimentResults, one per repo size
        """
        if repo_sizes is None:
            repo_sizes = ["small", "medium", "large"]

        if base_config is None:
            base_config = ProfileConfig(
                profile=WorkloadProfile.STEADY_STATE,
                duration_seconds=60,
                failures_per_interval=5,
            )

        results = []

        for size in repo_sizes:
            logger.info(f"Running scalability test with {size} repository")

            config = ProfileConfig(
                profile=base_config.profile,
                duration_seconds=base_config.duration_seconds,
                failures_per_interval=base_config.failures_per_interval,
                interval_seconds=base_config.interval_seconds,
                repo_size=size,
            )

            result = await self.run_throughput_experiment(config)
            result.experiment_type = "scalability"
            result.metadata["repo_size"] = size
            results.append(result)

            # Brief pause between size tests
            await asyncio.sleep(1)

        return results

    async def _mock_process(self, failure: Any) -> None:
        """
        Mock processing for experiments without real backend.

        Simulates processing delay and records metrics.

        Args:
            failure: The failure to process
        """
        # Simulate variable processing time
        delay = self._mock_process_delay_ms / 1000
        await asyncio.sleep(delay)

        # Record mock metrics
        metrics_collector.increment("failures_processed_total")

    async def _mock_process_with_retries(
        self,
        failure: Any,
        max_retries: int = 3,
    ) -> None:
        """
        Mock processing with retry logic for resilience tests.

        Args:
            failure: The failure to process
            max_retries: Maximum retry attempts

        Raises:
            Exception: If all retries exhausted
        """
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                await self._mock_process(failure)
                return
            except Exception as e:
                last_error = e
                metrics_collector.increment("retries_total")

                if attempt < max_retries:
                    # Exponential backoff
                    await asyncio.sleep(0.1 * (2**attempt))

        if last_error:
            raise last_error

    def generate_report(self, result: ExperimentResult) -> ExperimentReporter:
        """
        Create a reporter for the given result.

        Args:
            result: Experiment result to report on

        Returns:
            ExperimentReporter instance
        """
        return ExperimentReporter(result)

    def generate_comparison_report(
        self,
        results: list[ExperimentResult],
    ) -> str:
        """
        Generate a comparison report across multiple experiment results.

        Args:
            results: List of experiment results to compare

        Returns:
            Formatted comparison string
        """
        lines = [
            "=" * 70,
            "TerraFix Experiment Comparison Report",
            "=" * 70,
            "",
            f"{'Experiment':<20} {'Profile':<15} {'Processed':<12} {'Throughput':<15} {'Success %':<10}",
            "-" * 70,
        ]

        for r in results:
            lines.append(
                f"{r.experiment_type:<20} "
                f"{r.profile:<15} "
                f"{r.total_processed:<12} "
                f"{r.throughput_per_second:<15.2f} "
                f"{r.success_rate:<10.1f}"
            )

        lines.extend(
            [
                "",
                "=" * 70,
            ]
        )

        return "\n".join(lines)
