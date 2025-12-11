"""
Synthetic failure generator for TerraFix experiments.

This module generates realistic Vanta-like compliance failures
for testing and benchmarking the remediation pipeline without
requiring a live Vanta connection.

The generator creates failures that match the structure and
characteristics of real Vanta API responses, including:
- Realistic resource ARNs
- Proper compliance test metadata
- Configurable severity distribution
- Various resource types (S3, IAM, EC2, etc.)

Usage:
    from terrafix.experiments.generator import SyntheticFailureGenerator
    from terrafix.experiments.profiles import ProfileConfig, WorkloadProfile

    generator = SyntheticFailureGenerator()
    config = ProfileConfig(profile=WorkloadProfile.STEADY_STATE)

    # Generate a single failure
    failure = generator.generate_failure("AWS::S3::Bucket", "high")

    # Generate a stream of failures
    async for failure in generator.generate_stream(config):
        print(f"Generated: {failure.test_id}")
"""

import asyncio
import random
import string
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from terrafix.vanta_client import Failure

from .profiles import ProfileConfig


class SyntheticFailureGenerator:
    """
    Generator for synthetic Vanta compliance failures.

    Creates realistic test data for benchmarking and testing the
    TerraFix remediation pipeline without requiring live API access.

    Attributes:
        FAILURE_TEMPLATES: Predefined failure configurations by resource type

    Example:
        >>> generator = SyntheticFailureGenerator()
        >>> failure = generator.generate_failure("AWS::S3::Bucket", "high")
        >>> print(failure.test_name)
        'S3 Bucket Block Public Access'
    """

    FAILURE_TEMPLATES: dict[str, list[dict[str, Any]]] = {
        "AWS::S3::Bucket": [
            {
                "test_id": "s3-public-access-block",
                "test_name": "S3 Bucket Block Public Access",
                "failure_reason": "S3 bucket does not have public access blocked",
                "framework": "SOC2",
                "current_state": {
                    "block_public_acls": False,
                    "block_public_policy": False,
                    "ignore_public_acls": False,
                    "restrict_public_buckets": False,
                },
                "required_state": {
                    "block_public_acls": True,
                    "block_public_policy": True,
                    "ignore_public_acls": True,
                    "restrict_public_buckets": True,
                },
            },
            {
                "test_id": "s3-versioning-enabled",
                "test_name": "S3 Bucket Versioning",
                "failure_reason": "S3 bucket does not have versioning enabled",
                "framework": "SOC2",
                "current_state": {"versioning": "Disabled"},
                "required_state": {"versioning": "Enabled"},
            },
            {
                "test_id": "s3-encryption-at-rest",
                "test_name": "S3 Bucket Encryption",
                "failure_reason": "S3 bucket does not have server-side encryption",
                "framework": "ISO27001",
                "current_state": {"encryption": None},
                "required_state": {"encryption": "AES256"},
            },
        ],
        "AWS::IAM::Role": [
            {
                "test_id": "iam-session-duration",
                "test_name": "IAM Role Maximum Session Duration",
                "failure_reason": "IAM role session duration exceeds policy limit",
                "framework": "SOC2",
                "current_state": {"max_session_duration": 43200},
                "required_state": {"max_session_duration": 3600},
            },
            {
                "test_id": "iam-trust-policy",
                "test_name": "IAM Role Trust Policy Review",
                "failure_reason": "IAM role trust policy allows overly broad access",
                "framework": "SOC2",
                "current_state": {"trust_policy_principals": ["*"]},
                "required_state": {"trust_policy_principals": ["specific-service.amazonaws.com"]},
            },
        ],
        "AWS::EC2::SecurityGroup": [
            {
                "test_id": "sg-open-ssh",
                "test_name": "Security Group SSH Access",
                "failure_reason": "Security group allows SSH from 0.0.0.0/0",
                "framework": "SOC2",
                "current_state": {"ssh_cidr": "0.0.0.0/0"},
                "required_state": {"ssh_cidr": "10.0.0.0/8"},
            },
            {
                "test_id": "sg-open-rdp",
                "test_name": "Security Group RDP Access",
                "failure_reason": "Security group allows RDP from 0.0.0.0/0",
                "framework": "ISO27001",
                "current_state": {"rdp_cidr": "0.0.0.0/0"},
                "required_state": {"rdp_cidr": "10.0.0.0/8"},
            },
        ],
        "AWS::RDS::DBInstance": [
            {
                "test_id": "rds-encryption",
                "test_name": "RDS Encryption at Rest",
                "failure_reason": "RDS instance does not have encryption enabled",
                "framework": "SOC2",
                "current_state": {"storage_encrypted": False},
                "required_state": {"storage_encrypted": True},
            },
            {
                "test_id": "rds-public-access",
                "test_name": "RDS Public Accessibility",
                "failure_reason": "RDS instance is publicly accessible",
                "framework": "SOC2",
                "current_state": {"publicly_accessible": True},
                "required_state": {"publicly_accessible": False},
            },
        ],
    }

    def __init__(self, seed: int | None = None) -> None:
        """
        Initialize the generator.

        Args:
            seed: Optional random seed for reproducible generation
        """
        self._random = random.Random(seed)
        self._counter = 0

    def _generate_resource_id(self) -> str:
        """Generate a unique resource ID."""
        self._counter += 1
        suffix = "".join(self._random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"res-{self._counter:05d}-{suffix}"

    def _generate_bucket_name(self) -> str:
        """Generate a realistic S3 bucket name."""
        prefixes = ["data", "logs", "backup", "assets", "config", "staging", "prod"]
        prefix = self._random.choice(prefixes)
        suffix = "".join(self._random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"{prefix}-{suffix}"

    def _generate_role_name(self) -> str:
        """Generate a realistic IAM role name."""
        prefixes = ["lambda", "ecs", "ec2", "service", "app", "api"]
        suffixes = ["role", "execution-role", "task-role", "service-role"]
        prefix = self._random.choice(prefixes)
        suffix = self._random.choice(suffixes)
        name_part = "".join(self._random.choices(string.ascii_lowercase, k=6))
        return f"{prefix}-{name_part}-{suffix}"

    def _generate_sg_name(self) -> str:
        """Generate a realistic security group name."""
        prefixes = ["web", "app", "db", "bastion", "internal", "external"]
        prefix = self._random.choice(prefixes)
        suffix = "".join(self._random.choices(string.ascii_lowercase + string.digits, k=4))
        return f"{prefix}-sg-{suffix}"

    def _generate_arn(self, resource_type: str) -> str:
        """
        Generate a realistic ARN for the given resource type.

        Args:
            resource_type: AWS CloudFormation resource type

        Returns:
            Realistic ARN string
        """
        account_id = f"{self._random.randint(100000000000, 999999999999)}"
        region = self._random.choice(["us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1"])

        if resource_type == "AWS::S3::Bucket":
            bucket_name = self._generate_bucket_name()
            return f"arn:aws:s3:::{bucket_name}"

        elif resource_type == "AWS::IAM::Role":
            role_name = self._generate_role_name()
            return f"arn:aws:iam::{account_id}:role/{role_name}"

        elif resource_type == "AWS::EC2::SecurityGroup":
            sg_id = f"sg-{self._random.randint(10000000, 99999999):08x}"
            return f"arn:aws:ec2:{region}:{account_id}:security-group/{sg_id}"

        elif resource_type == "AWS::RDS::DBInstance":
            db_name = f"db-{''.join(self._random.choices(string.ascii_lowercase, k=8))}"
            return f"arn:aws:rds:{region}:{account_id}:db:{db_name}"

        # Fallback for unknown types
        resource_id = self._generate_resource_id()
        return f"arn:aws:unknown:{region}:{account_id}:resource/{resource_id}"

    def generate_failure(
        self,
        resource_type: str | None = None,
        severity: str | None = None,
    ) -> Failure:
        """
        Generate a single synthetic failure.

        Args:
            resource_type: Optional specific resource type to generate
            severity: Optional specific severity level

        Returns:
            Synthetic Failure object matching Vanta API structure
        """
        # Select resource type
        if resource_type is None:
            resource_type = self._random.choice(list(self.FAILURE_TEMPLATES.keys()))

        # Get templates for this resource type
        templates = self.FAILURE_TEMPLATES.get(
            resource_type, self.FAILURE_TEMPLATES["AWS::S3::Bucket"]
        )
        template = self._random.choice(templates)

        # Generate ARN and resource ID
        arn = self._generate_arn(resource_type)
        resource_id = self._generate_resource_id()

        # Select severity
        if severity is None:
            severity = self._random.choice(["critical", "high", "medium", "low"])

        # Generate timestamp
        failed_at = datetime.now(UTC).isoformat()

        # Extract resource name from ARN for details
        resource_name = arn.split("/")[-1] if "/" in arn else arn.split(":")[-1]

        return Failure(
            test_id=f"{template['test_id']}-{self._counter}",
            test_name=template["test_name"],
            resource_arn=arn,
            resource_type=resource_type,
            failure_reason=template["failure_reason"],
            severity=severity,
            framework=template["framework"],
            failed_at=failed_at,
            current_state=template["current_state"],
            required_state=template["required_state"],
            resource_id=resource_id,
            resource_details={"name": resource_name},
        )

    async def generate_stream(
        self,
        config: ProfileConfig,
    ) -> AsyncGenerator[Failure]:
        """
        Generate a stream of failures according to the profile configuration.

        Yields failures at intervals based on the workload profile,
        continuing until the configured duration expires.

        Args:
            config: Profile configuration controlling generation

        Yields:
            Failure objects at configured intervals

        Example:
            >>> async for failure in generator.generate_stream(config):
            ...     await process_failure(failure)
        """
        start_time = time.time()
        elapsed: float = 0.0

        while elapsed < config.duration_seconds:
            # Calculate failures for this interval
            num_failures = config.get_failures_for_interval(int(elapsed))

            # Generate and yield failures
            for _ in range(num_failures):
                # Select resource type based on config
                resource_type = self._random.choice(config.resource_types)

                # Select severity based on distribution
                severity = self._select_severity(config.severity_distribution)

                yield self.generate_failure(resource_type, severity)

            # Wait for next interval
            await asyncio.sleep(config.interval_seconds)
            elapsed = time.time() - start_time

    def _select_severity(self, distribution: dict[str, float]) -> str:
        """
        Select severity based on probability distribution.

        Args:
            distribution: Map of severity -> probability weight

        Returns:
            Selected severity level
        """
        severities = list(distribution.keys())
        weights = list(distribution.values())
        return self._random.choices(severities, weights=weights, k=1)[0]
