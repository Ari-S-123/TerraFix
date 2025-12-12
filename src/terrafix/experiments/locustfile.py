"""
Locust load testing configuration for TerraFix.

This module defines Locust user classes and tasks for load testing the TerraFix
service. It implements the three experiments outlined in the specification:

1. Pipeline Throughput and Bottleneck Identification
   - Measure end-to-end throughput at increasing rates
   - Identify bottlenecks (compute, I/O, or API-bound)
   - Collect P50/P95/P99 latency metrics

2. Concurrency and Failure Resilience
   - Test steady-state, burst, and cascade workloads
   - Verify deduplication under concurrent load
   - Measure retry success rates and recovery time

3. Repository Analysis Scalability
   - Test with small/medium/large repository profiles
   - Measure parsing time vs complexity
   - Track memory consumption patterns

Usage:
    # Start the mock API server first
    TERRAFIX_MOCK_MODE=true python -m terrafix.api_server

    # Run locust with web UI
    cd src/terrafix/experiments
    locust -f locustfile.py --host=http://localhost:8081

    # Run headless with specific parameters
    locust -f locustfile.py --host=http://localhost:8081 \
        --headless --users 10 --spawn-rate 2 --run-time 5m

    # Run specific experiment
    locust -f locustfile.py --host=http://localhost:8081 \
        --headless --users 50 --spawn-rate 5 --run-time 10m \
        --csv=results/throughput

Environment Variables:
    TERRAFIX_API_HOST: Target host (default: http://localhost:8081)
    TERRAFIX_EXPERIMENT: Experiment type (throughput, resilience, scalability)
    TERRAFIX_REPO_SIZE: Repository size profile (small, medium, large)
"""

from __future__ import annotations

import os
import random
import string
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

from locust import HttpUser, between, constant_pacing, events, task  # type: ignore[import-untyped]
from locust.runners import MasterRunner, WorkerRunner  # type: ignore[import-untyped]


# =============================================================================
# Synthetic Failure Generation
# =============================================================================


@dataclass
class FailureTemplate:
    """
    Template for generating synthetic compliance failures.

    Attributes:
        test_id: Base test identifier
        test_name: Human-readable test name
        resource_type: AWS resource type
        failure_reason: Description of the failure
        framework: Compliance framework (SOC2, ISO27001, etc.)
        current_state: Current resource state
        required_state: Required state for compliance
    """

    test_id: str
    test_name: str
    resource_type: str
    failure_reason: str
    framework: str
    current_state: dict[str, Any]
    required_state: dict[str, Any]


# Predefined failure templates
FAILURE_TEMPLATES: list[FailureTemplate] = [
    FailureTemplate(
        test_id="s3-public-access-block",
        test_name="S3 Bucket Block Public Access",
        resource_type="AWS::S3::Bucket",
        failure_reason="S3 bucket does not have public access blocked",
        framework="SOC2",
        current_state={
            "block_public_acls": False,
            "block_public_policy": False,
            "ignore_public_acls": False,
            "restrict_public_buckets": False,
        },
        required_state={
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True,
        },
    ),
    FailureTemplate(
        test_id="s3-versioning-enabled",
        test_name="S3 Bucket Versioning",
        resource_type="AWS::S3::Bucket",
        failure_reason="S3 bucket does not have versioning enabled",
        framework="SOC2",
        current_state={"versioning": "Disabled"},
        required_state={"versioning": "Enabled"},
    ),
    FailureTemplate(
        test_id="iam-session-duration",
        test_name="IAM Role Maximum Session Duration",
        resource_type="AWS::IAM::Role",
        failure_reason="IAM role session duration exceeds policy limit",
        framework="SOC2",
        current_state={"max_session_duration": 43200},
        required_state={"max_session_duration": 3600},
    ),
    FailureTemplate(
        test_id="sg-open-ssh",
        test_name="Security Group SSH Access",
        resource_type="AWS::EC2::SecurityGroup",
        failure_reason="Security group allows SSH from 0.0.0.0/0",
        framework="SOC2",
        current_state={"ssh_cidr": "0.0.0.0/0"},
        required_state={"ssh_cidr": "10.0.0.0/8"},
    ),
    FailureTemplate(
        test_id="rds-encryption",
        test_name="RDS Encryption at Rest",
        resource_type="AWS::RDS::DBInstance",
        failure_reason="RDS instance does not have encryption enabled",
        framework="SOC2",
        current_state={"storage_encrypted": False},
        required_state={"storage_encrypted": True},
    ),
]


def generate_unique_id(prefix: str = "") -> str:
    """
    Generate a unique identifier.

    Args:
        prefix: Optional prefix for the ID

    Returns:
        Unique string identifier
    """
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}{suffix}"


def generate_arn(resource_type: str) -> str:
    """
    Generate a realistic AWS ARN for the given resource type.

    Args:
        resource_type: AWS CloudFormation resource type

    Returns:
        Realistic ARN string
    """
    account_id = f"{random.randint(100000000000, 999999999999)}"
    region = random.choice(["us-east-1", "us-west-2", "eu-west-1"])

    if resource_type == "AWS::S3::Bucket":
        bucket_name = f"test-bucket-{generate_unique_id()}"
        return f"arn:aws:s3:::{bucket_name}"

    elif resource_type == "AWS::IAM::Role":
        role_name = f"test-role-{generate_unique_id()}"
        return f"arn:aws:iam::{account_id}:role/{role_name}"

    elif resource_type == "AWS::EC2::SecurityGroup":
        sg_id = f"sg-{random.randint(10000000, 99999999):08x}"
        return f"arn:aws:ec2:{region}:{account_id}:security-group/{sg_id}"

    elif resource_type == "AWS::RDS::DBInstance":
        db_name = f"db-{generate_unique_id()}"
        return f"arn:aws:rds:{region}:{account_id}:db:{db_name}"

    return f"arn:aws:unknown:{region}:{account_id}:resource/{generate_unique_id()}"


def generate_failure(
    template: FailureTemplate | None = None,
    severity: str | None = None,
    repo_size: str = "medium",
) -> dict[str, Any]:
    """
    Generate a synthetic compliance failure.

    Args:
        template: Optional specific template to use
        severity: Optional specific severity level
        repo_size: Repository size profile (affects complexity)

    Returns:
        Dictionary representing a Vanta failure
    """
    if template is None:
        template = random.choice(FAILURE_TEMPLATES)

    if severity is None:
        severity = random.choice(["critical", "high", "medium", "low"])

    arn = generate_arn(template.resource_type)
    resource_name = arn.split("/")[-1] if "/" in arn else arn.split(":")[-1]

    return {
        "test_id": f"{template.test_id}-{generate_unique_id()}",
        "test_name": template.test_name,
        "resource_arn": arn,
        "resource_type": template.resource_type,
        "failure_reason": template.failure_reason,
        "severity": severity,
        "framework": template.framework,
        "failed_at": datetime.now(UTC).isoformat(),
        "current_state": template.current_state,
        "required_state": template.required_state,
        "resource_id": f"res-{generate_unique_id()}",
        "resource_details": {
            "name": resource_name,
            "repo_size": repo_size,
        },
    }


# =============================================================================
# Locust User Classes
# =============================================================================


class TerraFixBaseUser(HttpUser):
    """
    Base user class for TerraFix load testing.

    Provides common functionality for all experiment types including
    failure generation and result tracking.

    Attributes:
        abstract: Marks this as a base class (not instantiated directly)
    """

    abstract = True

    # Class-level counters for aggregate statistics
    total_requests: ClassVar[int] = 0
    successful_requests: ClassVar[int] = 0
    failed_requests: ClassVar[int] = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize base user."""
        super().__init__(*args, **kwargs)
        self.repo_size = os.environ.get("TERRAFIX_REPO_SIZE", "medium")

    def submit_failure(
        self,
        failure: dict[str, Any] | None = None,
        name: str = "/webhook",
    ) -> bool:
        """
        Submit a failure to the TerraFix API.

        Args:
            failure: Optional failure data (generated if not provided)
            name: Name for the request in Locust stats

        Returns:
            True if request was successful
        """
        if failure is None:
            failure = generate_failure(repo_size=self.repo_size)

        with self.client.post(
            "/webhook",
            json=failure,
            name=name,
            catch_response=True,
        ) as response:
            TerraFixBaseUser.total_requests += 1

            if response.status_code == 200:
                TerraFixBaseUser.successful_requests += 1
                response.success()
                return True
            else:
                TerraFixBaseUser.failed_requests += 1
                response.failure(f"Status {response.status_code}: {response.text}")
                return False

    def submit_batch(
        self,
        count: int = 5,
        name: str = "/batch",
    ) -> bool:
        """
        Submit a batch of failures.

        Args:
            count: Number of failures in batch
            name: Name for the request in Locust stats

        Returns:
            True if request was successful
        """
        failures = [generate_failure(repo_size=self.repo_size) for _ in range(count)]

        with self.client.post(
            "/batch",
            json=failures,
            name=name,
            catch_response=True,
        ) as response:
            TerraFixBaseUser.total_requests += 1

            if response.status_code == 200:
                TerraFixBaseUser.successful_requests += 1
                response.success()
                return True
            else:
                TerraFixBaseUser.failed_requests += 1
                response.failure(f"Status {response.status_code}: {response.text}")
                return False


class ThroughputUser(TerraFixBaseUser):
    """
    User class for Experiment 1: Pipeline Throughput Testing.

    Generates steady load to measure maximum sustainable throughput
    and identify bottlenecks.

    Configuration:
        - Constant pacing: 1 request per second per user
        - Task: Submit single failures continuously
    """

    wait_time = constant_pacing(1)  # 1 request per second per user

    @task(weight=10)
    def submit_single_failure(self) -> None:
        """Submit a single compliance failure for processing."""
        self.submit_failure(name="/webhook [throughput]")

    @task(weight=1)
    def check_health(self) -> None:
        """Periodic health check to verify service availability."""
        self.client.get("/health", name="/health [throughput]")


class BurstUser(TerraFixBaseUser):
    """
    User class for Experiment 2: Burst/Stress Testing.

    Generates bursts of requests to test system behavior under
    sudden load spikes.

    Configuration:
        - Short wait times between bursts
        - Higher weight for batch submissions
    """

    wait_time = between(0.1, 0.5)  # Rapid-fire requests

    @task(weight=3)
    def submit_single_failure(self) -> None:
        """Submit a single failure rapidly."""
        self.submit_failure(name="/webhook [burst]")

    @task(weight=7)
    def submit_batch_failures(self) -> None:
        """Submit batch of failures for burst load."""
        batch_size = random.randint(5, 20)
        self.submit_batch(count=batch_size, name=f"/batch[{batch_size}] [burst]")


class ResilienceUser(TerraFixBaseUser):
    """
    User class for Experiment 2: Resilience Testing.

    Tests system resilience by submitting duplicate failures and
    verifying deduplication works under concurrent load.

    Configuration:
        - Moderate pacing with random variation
        - Mix of unique and duplicate failures
    """

    wait_time = between(0.5, 2.0)

    # Track submitted failures for deduplication testing
    _submitted_failures: ClassVar[list[dict[str, Any]]] = []
    _duplicate_rate: ClassVar[float] = 0.2  # 20% duplicates

    @task(weight=8)
    def submit_unique_failure(self) -> None:
        """Submit a unique failure."""
        failure = generate_failure(repo_size=self.repo_size)

        if len(ResilienceUser._submitted_failures) < 100:
            ResilienceUser._submitted_failures.append(failure)

        self.submit_failure(failure=failure, name="/webhook [resilience-unique]")

    @task(weight=2)
    def submit_duplicate_failure(self) -> None:
        """
        Submit a duplicate failure to test deduplication.

        The service should recognize duplicates and skip processing.
        """
        if ResilienceUser._submitted_failures:
            # Select a previously submitted failure
            failure = random.choice(ResilienceUser._submitted_failures)
            self.submit_failure(failure=failure, name="/webhook [resilience-duplicate]")
        else:
            # Fall back to unique if no history
            self.submit_unique_failure()


class ScalabilityUser(TerraFixBaseUser):
    """
    User class for Experiment 3: Scalability Testing.

    Tests performance across different repository sizes by varying
    the repo_size parameter in generated failures.

    Configuration:
        - Moderate pacing
        - Cycles through different repo sizes
    """

    wait_time = between(1.0, 3.0)

    REPO_SIZES: ClassVar[list[str]] = ["small", "medium", "large"]

    @task
    def submit_failure_varied_size(self) -> None:
        """Submit failures with varying repository sizes."""
        repo_size = random.choice(self.REPO_SIZES)
        failure = generate_failure(repo_size=repo_size)
        self.submit_failure(
            failure=failure,
            name=f"/webhook [scalability-{repo_size}]",
        )


class CascadeUser(TerraFixBaseUser):
    """
    User class for Cascade workload pattern.

    Simulates exponentially increasing failure rate to find
    system breaking points.

    Configuration:
        - Decreasing wait times over test duration
        - Increasing batch sizes
    """

    # Start slow, accelerate over time
    _start_time: ClassVar[float] = 0
    _cascade_factor: ClassVar[float] = 1.0

    def wait_time(self) -> float:
        """
        Calculate dynamic wait time based on cascade factor.

        Returns:
            Wait time in seconds (decreases over time)
        """
        # Base wait time that decreases as cascade progresses
        base_wait = max(0.1, 2.0 / CascadeUser._cascade_factor)
        return base_wait + random.uniform(0, 0.5)

    def on_start(self) -> None:
        """Initialize cascade timing."""
        if CascadeUser._start_time == 0:
            CascadeUser._start_time = time.time()

    @task
    def submit_cascading_failures(self) -> None:
        """Submit failures with increasing rate."""
        # Update cascade factor based on elapsed time
        elapsed = time.time() - CascadeUser._start_time
        CascadeUser._cascade_factor = 1.0 + (elapsed / 60)  # Increase every minute

        # Batch size increases with cascade factor
        batch_size = min(int(CascadeUser._cascade_factor * 2), 50)

        if batch_size > 1:
            self.submit_batch(count=batch_size, name=f"/batch [cascade-{batch_size}]")
        else:
            self.submit_failure(name="/webhook [cascade]")


class MixedWorkloadUser(TerraFixBaseUser):
    """
    User class for mixed/realistic workload simulation.

    Combines steady-state, occasional bursts, and varied repo sizes
    to simulate production-like traffic patterns.

    Configuration:
        - Variable wait times
        - Mixed task weights
    """

    wait_time = between(0.5, 5.0)

    @task(weight=60)
    def steady_state_request(self) -> None:
        """Normal steady-state single failure."""
        self.submit_failure(name="/webhook [mixed-steady]")

    @task(weight=20)
    def small_batch(self) -> None:
        """Occasional small batch."""
        self.submit_batch(count=3, name="/batch[3] [mixed]")

    @task(weight=10)
    def medium_batch(self) -> None:
        """Less frequent medium batch."""
        self.submit_batch(count=10, name="/batch[10] [mixed]")

    @task(weight=5)
    def large_batch(self) -> None:
        """Rare large batch."""
        self.submit_batch(count=25, name="/batch[25] [mixed]")

    @task(weight=5)
    def health_check(self) -> None:
        """Periodic health and status checks."""
        self.client.get("/health", name="/health [mixed]")
        self.client.get("/status", name="/status [mixed]")


# =============================================================================
# Event Handlers for Aggregate Statistics
# =============================================================================


@events.test_start.add_listener
def on_test_start(environment: Any, **kwargs: Any) -> None:
    """
    Reset counters at test start.

    Args:
        environment: Locust environment
        **kwargs: Additional arguments
    """
    TerraFixBaseUser.total_requests = 0
    TerraFixBaseUser.successful_requests = 0
    TerraFixBaseUser.failed_requests = 0
    CascadeUser._start_time = 0
    CascadeUser._cascade_factor = 1.0
    ResilienceUser._submitted_failures = []

    print("\n" + "=" * 60)
    print("TerraFix Load Test Started")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment: Any, **kwargs: Any) -> None:
    """
    Print summary statistics at test end.

    Args:
        environment: Locust environment
        **kwargs: Additional arguments
    """
    print("\n" + "=" * 60)
    print("TerraFix Load Test Completed")
    print("=" * 60)
    print(f"Total Requests: {TerraFixBaseUser.total_requests}")
    print(f"Successful: {TerraFixBaseUser.successful_requests}")
    print(f"Failed: {TerraFixBaseUser.failed_requests}")

    success_rate = (
        TerraFixBaseUser.successful_requests / TerraFixBaseUser.total_requests * 100
        if TerraFixBaseUser.total_requests > 0
        else 0
    )
    print(f"Success Rate: {success_rate:.1f}%")
    print("=" * 60)


@events.request.add_listener
def on_request(
    request_type: str,
    name: str,
    response_time: float,
    response_length: int,
    response: Any,
    exception: Exception | None,
    **kwargs: Any,
) -> None:
    """
    Log individual requests for detailed analysis.

    Args:
        request_type: HTTP method
        name: Request name
        response_time: Response time in ms
        response_length: Response body length
        response: Response object
        exception: Exception if request failed
        **kwargs: Additional arguments
    """
    # Only log failures for debugging
    if exception is not None:
        print(f"FAILED: {name} - {exception}")


# =============================================================================
# Distributed Testing Support
# =============================================================================


@events.init.add_listener
def on_locust_init(environment: Any, **kwargs: Any) -> None:
    """
    Initialize distributed testing support.

    Configures master/worker communication and aggregation.

    Args:
        environment: Locust environment
        **kwargs: Additional arguments
    """
    if isinstance(environment.runner, MasterRunner):
        print("Running as MASTER node")
    elif isinstance(environment.runner, WorkerRunner):
        print(f"Running as WORKER node")


# =============================================================================
# Default User Class Selection
# =============================================================================

# Select user class based on environment variable
_experiment = os.environ.get("TERRAFIX_EXPERIMENT", "throughput").lower()

if _experiment == "throughput":
    # Default to throughput testing
    class User(ThroughputUser):
        """Default user class for throughput testing."""
        pass

elif _experiment == "burst":
    class User(BurstUser):  # type: ignore[no-redef]
        """Default user class for burst testing."""
        pass

elif _experiment == "resilience":
    class User(ResilienceUser):  # type: ignore[no-redef]
        """Default user class for resilience testing."""
        pass

elif _experiment == "scalability":
    class User(ScalabilityUser):  # type: ignore[no-redef]
        """Default user class for scalability testing."""
        pass

elif _experiment == "cascade":
    class User(CascadeUser):  # type: ignore[no-redef]
        """Default user class for cascade testing."""
        pass

elif _experiment == "mixed":
    class User(MixedWorkloadUser):  # type: ignore[no-redef]
        """Default user class for mixed workload testing."""
        pass

else:
    # Fallback to throughput
    class User(ThroughputUser):  # type: ignore[no-redef]
        """Default user class (throughput)."""
        pass

