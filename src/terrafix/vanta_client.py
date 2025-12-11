"""
Vanta API client for polling compliance test failures.

This module provides a client for interacting with Vanta's REST API to
detect compliance test failures. The client handles OAuth authentication,
pagination, rate limiting, and deduplication hashing.

API Reference: https://developer.vanta.com/reference

OAuth Scopes:
    - vanta-api.all:read: Required for reading compliance data

Rate Limits (per Vanta documentation):
    - Management endpoints: 50 requests/minute
    - Integration endpoints: 20 requests/minute

Usage:
    from terrafix.vanta_client import VantaClient, Failure

    client = VantaClient(
        client_id="your_client_id",
        client_secret="your_client_secret"
    )
    failures = client.get_failing_tests()

    for failure in failures:
        failure_hash = client.generate_failure_hash(failure)
        print(f"Processing {failure.test_name} (hash: {failure_hash})")
"""

import hashlib
from datetime import datetime
from typing import Any, ClassVar, cast, override

import requests
from pydantic import BaseModel, Field

from terrafix.errors import VantaApiError
from terrafix.logging_config import get_logger, log_with_context
from terrafix.rate_limiter import VANTA_MANAGEMENT_LIMITER

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
    current_state: dict[str, object] = Field(
        default_factory=dict,
        description="Current resource configuration",
    )
    required_state: dict[str, object] = Field(
        default_factory=dict,
        description="Required configuration for compliance",
    )
    resource_id: str | None = Field(
        default=None,
        description="Optional Vanta resource ID used for enrichment when present",
    )
    resource_details: dict[str, object] = Field(
        default_factory=dict,
        description="Additional resource metadata",
    )

    @override
    def __str__(self) -> str:
        """Return human-readable string representation."""
        return f"Failure({self.test_name}, {self.resource_arn}, severity={self.severity})"


class VantaClient:
    """
    Client for interacting with Vanta's compliance API.

    The client handles OAuth 2.0 authentication using client credentials,
    pagination, rate limiting, and error handling. It maintains a persistent
    HTTP session for connection pooling.

    Authentication Flow:
        1. Exchange client_id and client_secret for access token
        2. Use Bearer token for all subsequent API requests
        3. Token refresh is handled automatically on 401 responses

    Attributes:
        base_url: Vanta API base URL (https://api.vanta.com)
        session: Persistent HTTP session for connection pooling
    """

    # Vanta API endpoints (based on developer.vanta.com/reference)
    OAUTH_TOKEN_ENDPOINT: ClassVar[str] = "/oauth/token"
    TESTS_ENDPOINT: ClassVar[str] = "/v1/tests"
    RESOURCES_ENDPOINT: ClassVar[str] = "/v1/resources"

    def __init__(
        self,
        api_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str = "https://api.vanta.com",
    ) -> None:
        """
        Initialize Vanta API client.

        Supports two authentication modes:
        1. Direct API token (for backwards compatibility)
        2. OAuth client credentials flow (recommended)

        Args:
            api_token: Pre-authenticated API token (legacy mode)
            client_id: OAuth client ID from Vanta Developer Console
            client_secret: OAuth client secret
            base_url: Vanta API base URL (default: https://api.vanta.com)

        Raises:
            VantaApiError: If authentication fails

        Example:
            >>> # Using OAuth (recommended)
            >>> client = VantaClient(
            ...     client_id="your_client_id",
            ...     client_secret="your_client_secret"
            ... )
            >>>
            >>> # Using direct token (legacy)
            >>> client = VantaClient(api_token="vanta_oauth_token")
        """
        self.base_url: str = base_url.rstrip("/")
        self.session: requests.Session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "TerraFix/0.1.0",
            }
        )

        # Store credentials for token refresh
        self._client_id: str | None = client_id
        self._client_secret: str | None = client_secret

        # Authenticate
        if api_token:
            # Legacy mode: use provided token directly
            self.session.headers["Authorization"] = f"Bearer {api_token}"
            log_with_context(
                logger,
                "info",
                "Initialized Vanta client with API token",
                base_url=self.base_url,
            )
        elif client_id and client_secret:
            # OAuth mode: exchange credentials for token
            self._authenticate_oauth()
        else:
            raise VantaApiError(
                "Must provide either api_token or both client_id and client_secret",
                retryable=False,
            )

    def _authenticate_oauth(self) -> None:
        """
        Obtain OAuth access token using client credentials flow.

        Uses the vanta-api.all:read scope as documented in Vanta's API.

        Raises:
            VantaApiError: If authentication fails
        """
        if not self._client_id or not self._client_secret:
            raise VantaApiError(
                "OAuth credentials not configured",
                retryable=False,
            )

        try:
            response = self.session.post(
                f"{self.base_url}{self.OAUTH_TOKEN_ENDPOINT}",
                json={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": "vanta-api.all:read",
                    "grant_type": "client_credentials",
                },
                timeout=30,
            )
            response.raise_for_status()

            token_data: dict[str, Any] = response.json()
            access_token: str | None = token_data.get("access_token")

            if not access_token:
                raise VantaApiError(
                    "No access token in authentication response",
                    retryable=False,
                )

            self.session.headers["Authorization"] = f"Bearer {access_token}"

            log_with_context(
                logger,
                "info",
                "Successfully authenticated with Vanta API via OAuth",
                base_url=self.base_url,
            )

        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            raise VantaApiError(
                f"Vanta OAuth authentication failed: {e}",
                status_code=status_code,
                retryable=False,
            ) from e
        except requests.RequestException as e:
            raise VantaApiError(
                f"Vanta authentication request failed: {e}",
                retryable=True,
            ) from e

    def _acquire_rate_limit(self, timeout: float = 120.0) -> None:
        """
        Acquire rate limit token before making an API request.

        Args:
            timeout: Maximum seconds to wait for rate limit token

        Raises:
            VantaApiError: If rate limit acquisition times out
        """
        if not VANTA_MANAGEMENT_LIMITER.acquire(timeout=timeout):
            raise VantaApiError(
                "Rate limit acquisition timeout - too many requests",
                retryable=True,
            )

    def get_failing_tests(
        self,
        frameworks: list[str] | None = None,
        since: datetime | None = None,
    ) -> list[Failure]:
        """
        Retrieve all currently failing tests.

        Polls Vanta API for all failing compliance tests, with optional
        filtering by framework and timestamp. Handles pagination automatically
        and respects rate limits.

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

        failures: list[Failure] = []
        page_cursor: str | None = None

        while True:
            # Acquire rate limit before each request
            self._acquire_rate_limit()

            params: dict[str, str | int] = {
                "status": "failing",
                "pageSize": 50,
            }

            if page_cursor:
                params["pageCursor"] = page_cursor

            if frameworks:
                params["frameworks"] = ",".join(frameworks)

            response_status: int | None = None
            response_body: str | None = None

            try:
                response = self.session.get(
                    f"{self.base_url}{self.TESTS_ENDPOINT}",
                    params=params,
                    timeout=30,
                )
                response_status = response.status_code
                response_body = response.text
                response.raise_for_status()

            except requests.HTTPError as e:
                # Always derive status/body from the HTTP response when available.
                status_code = e.response.status_code if e.response is not None else response_status
                body = e.response.text if e.response is not None else response_body

                # Handle 401 by attempting re-authentication
                if status_code == 401 and self._client_id and self._client_secret:
                    log_with_context(
                        logger,
                        "warning",
                        "Received 401, attempting re-authentication",
                    )
                    self._authenticate_oauth()
                    continue

                # Handle rate limiting
                if status_code == 429:
                    log_with_context(
                        logger,
                        "warning",
                        "Vanta API rate limit hit",
                    )
                    raise VantaApiError(
                        "Vanta API rate limit exceeded",
                        status_code=429,
                        retryable=True,
                    ) from e

                log_with_context(
                    logger,
                    "error",
                    "Vanta API request failed",
                    status_code=status_code,
                    response_body=body[:500] if body else None,
                )

                raise VantaApiError(
                    f"Vanta API request failed: {e}",
                    status_code=status_code,
                    response_body=body,
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

            data: dict[str, Any] = cast(dict[str, Any], response.json())
            results: dict[str, Any] = cast(dict[str, Any], data.get("results", {}))
            batch: list[dict[str, Any]] = cast(list[dict[str, Any]], results.get("data", []))

            # Filter by timestamp if provided
            if since:
                batch = [
                    t for t in batch if self._parse_timestamp(str(t.get("failed_at", ""))) > since
                ]

            # Convert to Failure objects with enrichment
            for failure_item in batch:
                try:
                    enriched = self._enrich_failure(failure_item)
                    failure = Failure(**enriched)
                    failures.append(failure)
                except Exception as e:
                    log_with_context(
                        logger,
                        "warning",
                        "Failed to parse failure",
                        error=str(e),
                        failure_data=failure_item,
                    )
                    # Continue processing other failures

            # Check for more pages
            page_info: dict[str, Any] = cast(dict[str, Any], results.get("pageInfo", {}))
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

    def _parse_timestamp(self, timestamp: str) -> datetime:
        """
        Parse ISO 8601 timestamp from Vanta API.

        Args:
            timestamp: ISO 8601 formatted timestamp string

        Returns:
            Parsed datetime object (returns epoch if parsing fails)
        """
        try:
            # Handle various ISO 8601 formats
            if timestamp.endswith("Z"):
                timestamp = timestamp[:-1] + "+00:00"
            return datetime.fromisoformat(timestamp)
        except (ValueError, TypeError):
            return datetime.min

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
                # Acquire rate limit for enrichment request
                self._acquire_rate_limit()

                resource_response = self.session.get(
                    f"{self.base_url}{self.RESOURCES_ENDPOINT}/{resource_id}",
                    timeout=30,
                )
                resource_response.raise_for_status()
                resource_data: dict[str, Any] = cast(dict[str, Any], resource_response.json())

                failure["resource_details"] = resource_data
                resource_id_str: str = str(resource_id)

                log_with_context(
                    logger,
                    "debug",
                    "Enriched failure with resource details",
                    resource_id=resource_id_str,
                )
            except requests.HTTPError as e:
                log_with_context(
                    logger,
                    "warning",
                    "Failed to enrich failure with resource details",
                    resource_id=str(resource_id),
                    status_code=e.response.status_code if e.response else None,
                )
                # Continue without enrichment
            except requests.RequestException as e:
                log_with_context(
                    logger,
                    "warning",
                    "Network error enriching failure",
                    resource_id=str(resource_id),
                    error=str(e),
                )
                # Continue without enrichment
            except VantaApiError:
                # Rate limit timeout during enrichment - skip enrichment
                log_with_context(
                    logger,
                    "warning",
                    "Rate limit timeout during enrichment, skipping",
                    resource_id=str(resource_id),
                )

        return failure

    def generate_failure_hash(self, failure: Failure) -> str:
        """
        Generate deterministic hash for deduplication.

        Creates a SHA256 hash from the failure signature using test_id and
        resource_arn only. The timestamp is intentionally excluded to ensure
        that recurring failures for the same issue produce the same hash,
        preventing duplicate PRs when issues regress.

        Args:
            failure: Test failure object

        Returns:
            SHA256 hash (hex string) of failure signature

        Example:
            >>> failure_hash = client.generate_failure_hash(failure)
            >>> print(f"Hash: {failure_hash}")

        Note:
            The hash excludes failed_at timestamp to prevent duplicate PRs
            when the same compliance issue recurs after being fixed.
        """
        # Exclude timestamp to prevent duplicates on regression
        # Only test_id and resource_arn identify a unique compliance issue
        signature = f"{failure.test_id}-{failure.resource_arn}"
        return hashlib.sha256(signature.encode()).hexdigest()
