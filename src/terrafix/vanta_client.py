"""
Vanta API client for polling compliance test failures.

This module provides a client for interacting with Vanta's REST API to
detect compliance test failures. The client handles pagination, enrichment,
and deduplication hashing.

The VantaClient polls Vanta's API for failing tests without requiring any
AWS access. It only needs read-only access to Vanta's test results.

Usage:
    from terrafix.vanta_client import VantaClient, Failure

    client = VantaClient(api_token="vanta_oauth_token")
    failures = client.get_failing_tests(frameworks=["SOC2", "ISO27001"])

    for failure in failures:
        failure_hash = client.generate_failure_hash(failure)
        print(f"Processing {failure.test_name} (hash: {failure_hash})")
"""

import hashlib
from datetime import datetime
from typing import Any

import requests
from pydantic import BaseModel, Field

from terrafix.errors import VantaApiError
from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


class Failure(BaseModel):
    """
    Vanta compliance test failure.

    Represents a single compliance test failure detected by Vanta.
    Contains all information needed to remediate the failure via
    Terraform changes.

    Attributes:
        test_id: Unique test identifier from Vanta
        test_name: Human-readable test name
        resource_arn: AWS resource ARN (if applicable)
        resource_type: AWS resource type (AWS::S3::Bucket, etc.)
        failure_reason: Why the test failed
        severity: Severity level (high/medium/low)
        framework: Compliance framework (SOC2, ISO27001, etc.)
        failed_at: ISO 8601 timestamp when test failed
        current_state: Current resource configuration
        required_state: Required configuration for compliance
        resource_id: Vanta resource ID for enrichment
        resource_details: Additional resource metadata from Vanta
    """

    test_id: str = Field(..., description="Unique test identifier")
    test_name: str = Field(..., description="Human-readable test name")
    resource_arn: str = Field(..., description="AWS resource ARN")
    resource_type: str = Field(..., description="AWS resource type")
    failure_reason: str = Field(..., description="Why the test failed")
    severity: str = Field(..., description="Severity (high/medium/low)")
    framework: str = Field(..., description="Compliance framework")
    failed_at: str = Field(..., description="ISO 8601 timestamp")
    current_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Current resource configuration",
    )
    required_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Required configuration for compliance",
    )
    resource_id: str | None = Field(None, description="Vanta resource ID")
    resource_details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional resource metadata",
    )

    def __str__(self) -> str:
        """Return human-readable string representation."""
        return f"Failure({self.test_name}, {self.resource_arn}, severity={self.severity})"


class VantaClient:
    """
    Client for interacting with Vanta's compliance API.

    The client handles authentication, pagination, enrichment, and error
    handling for the Vanta API. It maintains a persistent HTTP session
    for connection pooling.

    Attributes:
        api_token: OAuth token for Vanta API authentication
        base_url: Vanta API base URL (https://api.vanta.com)
        session: Persistent HTTP session for connection pooling
    """

    def __init__(self, api_token: str, base_url: str = "https://api.vanta.com") -> None:
        """
        Initialize Vanta API client.

        Args:
            api_token: Vanta OAuth token with test:read scope
            base_url: Vanta API base URL (default: https://api.vanta.com)

        Example:
            >>> client = VantaClient(api_token="vanta_oauth_token")
        """
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "User-Agent": "TerraFix/0.1.0",
            }
        )

        log_with_context(
            logger,
            "info",
            "Initialized Vanta client",
            base_url=self.base_url,
        )

    def get_failing_tests(
        self,
        frameworks: list[str] | None = None,
        since: datetime | None = None,
    ) -> list[Failure]:
        """
        Retrieve all currently failing tests.

        Polls Vanta API for all failing compliance tests, with optional
        filtering by framework and timestamp. Handles pagination automatically.

        Args:
            frameworks: Filter by framework (SOC2, ISO27001, etc.)
            since: Only return failures since this timestamp

        Returns:
            List of Failure objects

        Raises:
            VantaApiError: If API request fails

        Example:
            >>> failures = client.get_failing_tests(frameworks=["SOC2"])
            >>> print(f"Found {len(failures)} failures")
        """
        log_with_context(
            logger,
            "info",
            "Fetching failing tests from Vanta",
            frameworks=frameworks,
            since=since.isoformat() if since else None,
        )

        failures = []
        page_cursor = None

        while True:
            params: dict[str, Any] = {
                "status": "failing",
                "pageSize": 50,
            }

            if page_cursor:
                params["pageCursor"] = page_cursor

            if frameworks:
                params["frameworks"] = ",".join(frameworks)

            try:
                response = self.session.get(
                    f"{self.base_url}/v1/tests",
                    params=params,
                    timeout=30,
                )
                response.raise_for_status()
            except requests.HTTPError as e:
                status_code = e.response.status_code if e.response else None
                response_body = e.response.text if e.response else None

                log_with_context(
                    logger,
                    "error",
                    "Vanta API request failed",
                    status_code=status_code,
                    response_body=response_body[:500] if response_body else None,
                )

                raise VantaApiError(
                    f"Vanta API request failed: {e}",
                    status_code=status_code,
                    response_body=response_body,
                    retryable=(status_code is None or status_code >= 500),
                ) from e
            except requests.RequestException as e:
                log_with_context(
                    logger,
                    "error",
                    "Vanta API network error",
                    error=str(e),
                )
                raise VantaApiError(
                    f"Vanta API network error: {e}",
                    retryable=True,
                ) from e

            data = response.json()
            batch = data.get("results", {}).get("data", [])

            # Filter by timestamp if provided
            if since:
                batch = [
                    t for t in batch if datetime.fromisoformat(t["failed_at"]) > since
                ]

            # Convert to Failure objects with enrichment
            for failure_data in batch:
                try:
                    enriched = self._enrich_failure(failure_data)
                    failure = Failure(**enriched)
                    failures.append(failure)
                except Exception as e:
                    log_with_context(
                        logger,
                        "warning",
                        "Failed to parse failure",
                        error=str(e),
                        failure_data=failure_data,
                    )
                    # Continue processing other failures

            # Check for more pages
            page_info = data.get("results", {}).get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break

            page_cursor = page_info.get("endCursor")

        log_with_context(
            logger,
            "info",
            "Fetched failing tests from Vanta",
            count=len(failures),
        )

        return failures

    def get_failing_tests_since(self, last_check: datetime | None) -> list[Failure]:
        """
        Retrieve failing tests since last check.

        Convenience method for the service loop that polls for new failures.

        Args:
            last_check: Last polling timestamp (None for all failures)

        Returns:
            List of Failure objects since last check

        Raises:
            VantaApiError: If API request fails

        Example:
            >>> from datetime import datetime, timedelta
            >>> last_check = datetime.now() - timedelta(hours=1)
            >>> new_failures = client.get_failing_tests_since(last_check)
        """
        return self.get_failing_tests(since=last_check)

    def _enrich_failure(self, failure: dict[str, Any]) -> dict[str, Any]:
        """
        Enrich failure with additional resource metadata.

        Fetches detailed resource information from Vanta if a resource_id
        is present. Enrichment failures are logged but don't fail the
        entire operation.

        Args:
            failure: Basic failure object from Vanta

        Returns:
            Enriched failure with resource details

        Example:
            >>> enriched = client._enrich_failure({"test_id": "123", ...})
        """
        resource_id = failure.get("resource_id")
        if resource_id:
            try:
                resource_response = self.session.get(
                    f"{self.base_url}/v1/resources/{resource_id}",
                    timeout=30,
                )
                resource_response.raise_for_status()
                resource_data = resource_response.json()

                failure["resource_details"] = resource_data

                log_with_context(
                    logger,
                    "debug",
                    "Enriched failure with resource details",
                    resource_id=resource_id,
                )
            except requests.HTTPError as e:
                log_with_context(
                    logger,
                    "warning",
                    "Failed to enrich failure with resource details",
                    resource_id=resource_id,
                    status_code=e.response.status_code if e.response else None,
                )
                # Continue without enrichment
            except requests.RequestException as e:
                log_with_context(
                    logger,
                    "warning",
                    "Network error enriching failure",
                    resource_id=resource_id,
                    error=str(e),
                )
                # Continue without enrichment

        return failure

    def generate_failure_hash(self, failure: Failure) -> str:
        """
        Generate deterministic hash for deduplication.

        Creates a SHA256 hash from the failure signature (test_id, resource_arn,
        and failed_at timestamp). This hash is used by the state store to
        detect and skip duplicate failures.

        Args:
            failure: Test failure object

        Returns:
            SHA256 hash (hex string) of failure signature

        Example:
            >>> failure_hash = client.generate_failure_hash(failure)
            >>> print(f"Hash: {failure_hash}")
        """
        signature = f"{failure.test_id}-{failure.resource_arn}-{failure.failed_at}"
        return hashlib.sha256(signature.encode()).hexdigest()

