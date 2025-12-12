"""
TerraFix Experiment Harness.

This package provides tools for testing and benchmarking the TerraFix
remediation pipeline with synthetic workloads and controlled failure injection.

Components:
    - SyntheticFailureGenerator: Generate realistic Vanta-like failures
    - WorkloadProfile: Configurable workload patterns (steady, burst, cascade)
    - FailureInjector: Inject failures for resilience testing
    - ExperimentRunner: Orchestrate experiment execution
    - ExperimentReporter: Generate reports and export results
    - ExperimentChartGenerator: Generate charts and visualizations
    - run_experiments: CLI for running load tests with Locust

Usage:
    from terrafix.experiments import (
        SyntheticFailureGenerator,
        WorkloadProfile,
        ProfileConfig,
        FailureInjector,
        ExperimentRunner,
        ExperimentReporter,
        ExperimentResult,
    )

    # Quick experiment setup
    runner = ExperimentRunner()
    config = ProfileConfig(profile=WorkloadProfile.STEADY_STATE)
    result = await runner.run_throughput_experiment(config)
    print(ExperimentReporter(result).generate_summary())

CLI Usage:
    # Run in-process throughput test
    python -m terrafix.experiments run --type throughput --preset baseline

    # Run resilience test
    python -m terrafix.experiments run --type resilience --failure-rate 0.2

    # Generate report
    python -m terrafix.experiments report --input results.json

    # Run Locust load tests (recommended for deployed services)
    python -m terrafix.experiments.run_experiments --local

    # Run against deployed service
    python -m terrafix.experiments.run_experiments --host https://terrafix.example.com
"""

from .generator import SyntheticFailureGenerator
from .injector import FailureInjector
from .profiles import PRESETS, ProfileConfig, WorkloadProfile
from .reporter import ExperimentReporter, ExperimentResult
from .runner import ExperimentRunner

__all__ = [
    # Generator
    "SyntheticFailureGenerator",
    # Profiles
    "WorkloadProfile",
    "ProfileConfig",
    "PRESETS",
    # Injector
    "FailureInjector",
    # Reporter
    "ExperimentResult",
    "ExperimentReporter",
    # Runner
    "ExperimentRunner",
]

# Lazy imports for optional dependencies (charts require matplotlib)
def __getattr__(name: str) -> object:
    """
    Lazy import for optional modules.

    Args:
        name: Attribute name to import

    Returns:
        Imported module or raises AttributeError
    """
    if name == "ExperimentChartGenerator":
        from .charts import ExperimentChartGenerator
        return ExperimentChartGenerator
    if name == "ChartConfig":
        from .charts import ChartConfig
        return ChartConfig
    if name == "ExperimentData":
        from .charts import ExperimentData
        return ExperimentData
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
