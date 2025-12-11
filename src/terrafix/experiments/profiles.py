"""
Workload profiles for TerraFix experiment harness.

This module defines configurable workload patterns for generating
synthetic compliance failures during experiments. Profiles control
the rate, distribution, and characteristics of generated failures.

Profiles:
    STEADY_STATE: Constant rate of failures (baseline testing)
    BURST: Periodic spikes followed by quiet periods (stress testing)
    CASCADE: Exponentially increasing failures (resilience testing)

Usage:
    from terrafix.experiments.profiles import WorkloadProfile, ProfileConfig

    config = ProfileConfig(
        profile=WorkloadProfile.BURST,
        duration_seconds=300,
        failures_per_interval=10,
    )
"""

from dataclasses import dataclass, field
from enum import Enum


class WorkloadProfile(str, Enum):
    """
    Predefined workload patterns for experiments.

    Each profile generates failures with different timing characteristics
    to test various aspects of system behavior.

    Attributes:
        STEADY_STATE: Constant rate of failures over time.
            Best for: Baseline performance measurement
        BURST: High-volume spikes followed by quiet periods.
            Best for: Stress testing and queue behavior
        CASCADE: Exponentially increasing failure rate.
            Best for: Finding breaking points and limits
    """

    STEADY_STATE = "steady_state"
    BURST = "burst"
    CASCADE = "cascade"


@dataclass
class ProfileConfig:
    """
    Configuration for an experiment workload profile.

    Controls how synthetic failures are generated during an experiment,
    including timing, volume, and resource characteristics.

    Attributes:
        profile: The workload pattern to use
        duration_seconds: Total experiment duration
        failures_per_interval: Base number of failures per interval
        interval_seconds: Time between failure batches
        burst_multiplier: Multiplier for burst profile spikes
        burst_duration_seconds: Duration of burst periods
        cascade_growth_rate: Growth rate for cascade profile (multiplier per interval)
        resource_types: Types of resources to include in failures
        severity_distribution: Probability weights for severity levels
        repo_size: Size category for synthetic terraform repos
        include_validation_errors: Whether to inject validation failures

    Example:
        >>> config = ProfileConfig(
        ...     profile=WorkloadProfile.BURST,
        ...     duration_seconds=600,
        ...     failures_per_interval=5,
        ...     burst_multiplier=10,
        ... )
    """

    profile: WorkloadProfile = WorkloadProfile.STEADY_STATE
    duration_seconds: int = 300
    failures_per_interval: int = 5
    interval_seconds: int = 10
    burst_multiplier: int = 10
    burst_duration_seconds: int = 30
    cascade_growth_rate: float = 1.5
    resource_types: list[str] = field(
        default_factory=lambda: [
            "AWS::S3::Bucket",
            "AWS::IAM::Role",
            "AWS::EC2::SecurityGroup",
        ]
    )
    severity_distribution: dict[str, float] = field(
        default_factory=lambda: {
            "critical": 0.1,
            "high": 0.3,
            "medium": 0.4,
            "low": 0.2,
        }
    )
    repo_size: str = "medium"  # small, medium, large
    include_validation_errors: bool = False

    def get_failures_for_interval(self, elapsed_seconds: int) -> int:
        """
        Calculate number of failures to generate for current interval.

        Uses the profile configuration to determine how many failures
        should be generated based on elapsed time.

        Args:
            elapsed_seconds: Time elapsed since experiment start

        Returns:
            Number of failures to generate this interval
        """
        if self.profile == WorkloadProfile.STEADY_STATE:
            return self.failures_per_interval

        elif self.profile == WorkloadProfile.BURST:
            # Burst every burst_duration_seconds
            cycle_position = elapsed_seconds % (self.burst_duration_seconds * 2)
            if cycle_position < self.burst_duration_seconds:
                return self.failures_per_interval * self.burst_multiplier
            return self.failures_per_interval

        elif self.profile == WorkloadProfile.CASCADE:
            # Exponential growth
            intervals_elapsed = elapsed_seconds // self.interval_seconds
            multiplier = self.cascade_growth_rate**intervals_elapsed
            return int(self.failures_per_interval * multiplier)

        return self.failures_per_interval


# Preset configurations for common experiment scenarios
PRESETS: dict[str, ProfileConfig] = {
    "quick_test": ProfileConfig(
        profile=WorkloadProfile.STEADY_STATE,
        duration_seconds=60,
        failures_per_interval=2,
        interval_seconds=10,
    ),
    "baseline": ProfileConfig(
        profile=WorkloadProfile.STEADY_STATE,
        duration_seconds=300,
        failures_per_interval=5,
        interval_seconds=10,
    ),
    "stress_test": ProfileConfig(
        profile=WorkloadProfile.BURST,
        duration_seconds=600,
        failures_per_interval=5,
        burst_multiplier=20,
        burst_duration_seconds=30,
    ),
    "resilience_test": ProfileConfig(
        profile=WorkloadProfile.CASCADE,
        duration_seconds=300,
        failures_per_interval=2,
        cascade_growth_rate=1.5,
    ),
    "production_like": ProfileConfig(
        profile=WorkloadProfile.STEADY_STATE,
        duration_seconds=3600,
        failures_per_interval=10,
        interval_seconds=60,
        repo_size="large",
    ),
}
