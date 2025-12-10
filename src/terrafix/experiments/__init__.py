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
    # Run throughput test
    python -m terrafix.experiments run --type throughput --preset baseline

    # Run resilience test
    python -m terrafix.experiments run --type resilience --failure-rate 0.2

    # Generate report
    python -m terrafix.experiments report --input results.json
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

