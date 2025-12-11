"""
Unit tests for VantaClient.

Tests cover OAuth authentication, API requests, pagination handling,
rate limiting, error handling, and failure hash generation.
"""

from datetime import UTC, datetime, timedelta

import pytest
import responses
from responses import matchers

from terrafix.errors import VantaApiError
from terrafix.vanta_client import Failure, VantaClient


class TestFailureModel:
    """Tests for the Failure Pydantic model."""

    def test_failure_creation_with_required_fields(self) -> None:
        """Test creating a Failure with all required fields."""
        failure = Failure(
            test_id="test-123",
            test_name="Test Name",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Test reason",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
            resource_id="res-123",
        )

        assert failure.test_id == "test-123"
        assert failure.test_name == "Test Name"
        assert failure.resource_arn == "arn:aws:s3:::bucket"
        assert failure.resource_type == "AWS::S3::Bucket"
        assert failure.failure_reason == "Test reason"
        assert failure.severity == "high"
        assert failure.framework == "SOC2"
        assert failure.failed_at == "2025-01-15T10:00:00Z"

    def test_failure_default_values(self) -> None:
        """Test that optional fields have correct defaults."""
        failure = Failure(
            test_id="test-123",
            test_name="Test Name",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Test reason",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
        )

        assert failure.current_state == {}
        assert failure.required_state == {}
        assert failure.resource_id is None
        assert failure.resource_details == {}

    def test_failure_with_state_dicts(self) -> None:
        """Test Failure with current and required state."""
        current: dict[str, object] = {"block_public_acls": False}
        required: dict[str, object] = {"block_public_acls": True}

        failure = Failure(
            test_id="test-123",
            test_name="Test Name",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Test reason",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
            current_state=current,
            required_state=required,
            resource_id="res-123",
        )

        assert failure.current_state == current
        assert failure.required_state == required

    def test_failure_str_representation(self, sample_failure: Failure) -> None:
        """Test the string representation of a Failure."""
        str_repr = str(sample_failure)
        assert "Failure(" in str_repr
        assert sample_failure.test_name in str_repr
        assert sample_failure.resource_arn in str_repr
        assert sample_failure.severity in str_repr


class TestVantaClientInit:
    """Tests for VantaClient initialization."""

    @responses.activate
    def test_init_with_api_token(self) -> None:
        """Test initialization with direct API token."""
        client = VantaClient(api_token="test_token")

        assert client.base_url == "https://api.vanta.com"
        assert client.session.headers["Authorization"] == "Bearer test_token"

    @responses.activate
    def test_init_with_oauth_credentials(self) -> None:
        """Test initialization with OAuth client credentials."""
        _ = responses.add(
            responses.POST,
            "https://api.vanta.com/oauth/token",
            json={
                "access_token": "oauth_access_token",
                "token_type": "bearer",
                "expires_in": 3600,
            },
            status=200,
        )

        client = VantaClient(
            client_id="test_client_id",
            client_secret="test_client_secret",
        )

        assert client.session.headers["Authorization"] == "Bearer oauth_access_token"

    def test_init_without_credentials_raises(self) -> None:
        """Test that init without credentials raises error."""
        with pytest.raises(VantaApiError) as exc_info:
            _ = VantaClient()

        assert "Must provide either api_token" in str(exc_info.value)
        assert exc_info.value.retryable is False

    @responses.activate
    def test_init_with_custom_base_url(self) -> None:
        """Test initialization with custom base URL."""
        client = VantaClient(
            api_token="test_token",
            base_url="https://custom.vanta.com/",
        )

        # Should strip trailing slash
        assert client.base_url == "https://custom.vanta.com"

    @responses.activate
    def test_oauth_failure_raises_error(self) -> None:
        """Test that OAuth authentication failure raises error."""
        _ = responses.add(
            responses.POST,
            "https://api.vanta.com/oauth/token",
            json={"error": "invalid_client"},
            status=401,
        )

        with pytest.raises(VantaApiError) as exc_info:
            _ = VantaClient(
                client_id="invalid_client",
                client_secret="invalid_secret",
            )

        assert exc_info.value.retryable is False


class TestVantaClientGetFailingTests:
    """Tests for VantaClient.get_failing_tests method."""

    @responses.activate
    def test_get_failing_tests_success(
        self,
        sample_vanta_api_response: dict[str, object],
    ) -> None:
        """Test successful retrieval of failing tests."""
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json=sample_vanta_api_response,
            status=200,
        )

        client = VantaClient(api_token="test_token")
        failures = client.get_failing_tests()

        assert len(failures) == 1
        assert failures[0].test_id == "test-s3-001"
        assert failures[0].test_name == "S3 Bucket Block Public Access"

    @responses.activate
    def test_get_failing_tests_with_framework_filter(self) -> None:
        """Test filtering by framework."""
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json={"results": {"data": [], "pageInfo": {"hasNextPage": False}}},
            status=200,
            match=[matchers.query_param_matcher({"status": "failing", "pageSize": "50", "frameworks": "SOC2"}, strict_match=False)],
        )

        client = VantaClient(api_token="test_token")
        failures = client.get_failing_tests(frameworks=["SOC2"])

        assert failures == []

    @responses.activate
    def test_get_failing_tests_pagination(self) -> None:
        """Test pagination handling."""
        # First page with hasNextPage=True
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json={
                "results": {
                    "data": [
                        {
                            "test_id": "test-1",
                            "test_name": "Test 1",
                            "resource_arn": "arn:aws:s3:::bucket1",
                            "resource_type": "AWS::S3::Bucket",
                            "failure_reason": "Reason 1",
                            "severity": "high",
                            "framework": "SOC2",
                            "failed_at": "2025-01-15T10:00:00Z",
                        }
                    ],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor123"},
                }
            },
            status=200,
        )

        # Second page with hasNextPage=False
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json={
                "results": {
                    "data": [
                        {
                            "test_id": "test-2",
                            "test_name": "Test 2",
                            "resource_arn": "arn:aws:s3:::bucket2",
                            "resource_type": "AWS::S3::Bucket",
                            "failure_reason": "Reason 2",
                            "severity": "medium",
                            "framework": "SOC2",
                            "failed_at": "2025-01-15T11:00:00Z",
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            },
            status=200,
        )

        client = VantaClient(api_token="test_token")
        failures = client.get_failing_tests()

        assert len(failures) == 2
        assert failures[0].test_id == "test-1"
        assert failures[1].test_id == "test-2"

    @responses.activate
    def test_get_failing_tests_since_timestamp(self) -> None:
        """Test filtering by timestamp."""
        since_time = datetime(2025, 1, 15, 9, 0, 0, tzinfo=UTC)

        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json={
                "results": {
                    "data": [
                        {
                            "test_id": "test-old",
                            "test_name": "Old Test",
                            "resource_arn": "arn:aws:s3:::old",
                            "resource_type": "AWS::S3::Bucket",
                            "failure_reason": "Old",
                            "severity": "high",
                            "framework": "SOC2",
                            "failed_at": "2025-01-15T08:00:00Z",  # Before since_time
                        },
                        {
                            "test_id": "test-new",
                            "test_name": "New Test",
                            "resource_arn": "arn:aws:s3:::new",
                            "resource_type": "AWS::S3::Bucket",
                            "failure_reason": "New",
                            "severity": "high",
                            "framework": "SOC2",
                            "failed_at": "2025-01-15T10:00:00Z",  # After since_time
                        },
                    ],
                    "pageInfo": {"hasNextPage": False},
                }
            },
            status=200,
        )

        client = VantaClient(api_token="test_token")
        failures = client.get_failing_tests(since=since_time)

        # Should only return the test after since_time
        assert len(failures) == 1
        assert failures[0].test_id == "test-new"

    @responses.activate
    def test_get_failing_tests_http_error(self) -> None:
        """Test handling of HTTP errors."""
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json={"error": "Internal Server Error"},
            status=500,
        )

        client = VantaClient(api_token="test_token")

        with pytest.raises(VantaApiError) as exc_info:
            _ = client.get_failing_tests()

        assert exc_info.value.status_code == 500
        assert exc_info.value.retryable is True

    @responses.activate
    def test_get_failing_tests_rate_limit_error(self) -> None:
        """Test handling of rate limit errors."""
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json={"error": "Rate limit exceeded"},
            status=429,
        )

        client = VantaClient(api_token="test_token")

        with pytest.raises(VantaApiError) as exc_info:
            _ = client.get_failing_tests()

        assert exc_info.value.status_code == 429
        assert exc_info.value.retryable is True

    @responses.activate
    def test_get_failing_tests_401_triggers_reauth(self) -> None:
        """Test that 401 triggers re-authentication with OAuth."""
        # First call returns 401
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json={"error": "Unauthorized"},
            status=401,
        )

        # OAuth re-authentication
        _ = responses.add(
            responses.POST,
            "https://api.vanta.com/oauth/token",
            json={
                "access_token": "new_oauth_token",
                "token_type": "bearer",
            },
            status=200,
        )

        # Retry after re-auth succeeds
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json={"results": {"data": [], "pageInfo": {"hasNextPage": False}}},
            status=200,
        )

        # Initialize with OAuth first
        _ = responses.add(
            responses.POST,
            "https://api.vanta.com/oauth/token",
            json={
                "access_token": "initial_oauth_token",
                "token_type": "bearer",
            },
            status=200,
        )

        client = VantaClient(
            client_id="test_client",
            client_secret="test_secret",
        )

        # Should succeed after re-auth
        failures = client.get_failing_tests()
        assert failures == []


class TestVantaClientGenerateFailureHash:
    """Tests for VantaClient.generate_failure_hash method."""

    @responses.activate
    def test_generate_failure_hash_deterministic(
        self,
        sample_failure: Failure,
    ) -> None:
        """Test that hash generation is deterministic."""
        client = VantaClient(api_token="test_token")

        hash1 = client.generate_failure_hash(sample_failure)
        hash2 = client.generate_failure_hash(sample_failure)

        assert hash1 == hash2

    @responses.activate
    def test_generate_failure_hash_format(
        self,
        sample_failure: Failure,
    ) -> None:
        """Test that hash is a valid SHA256 hex string."""
        client = VantaClient(api_token="test_token")

        failure_hash = client.generate_failure_hash(sample_failure)

        # SHA256 produces 64 character hex string
        assert len(failure_hash) == 64
        assert all(c in "0123456789abcdef" for c in failure_hash)

    @responses.activate
    def test_generate_failure_hash_excludes_timestamp(self) -> None:
        """Test that hash excludes timestamp to prevent duplicate PRs."""
        client = VantaClient(api_token="test_token")

        failure1 = Failure(
            test_id="test-123",
            test_name="Test",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Reason",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",  # Different timestamp
            resource_id="res-123",
        )

        failure2 = Failure(
            test_id="test-123",
            test_name="Test",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Reason",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-16T11:00:00Z",  # Different timestamp
            resource_id="res-123",
        )

        hash1 = client.generate_failure_hash(failure1)
        hash2 = client.generate_failure_hash(failure2)

        # Hashes should be equal because timestamp is excluded
        assert hash1 == hash2

    @responses.activate
    def test_generate_failure_hash_different_resources(self) -> None:
        """Test that different resources produce different hashes."""
        client = VantaClient(api_token="test_token")

        failure1 = Failure(
            test_id="test-123",
            test_name="Test",
            resource_arn="arn:aws:s3:::bucket1",  # Different ARN
            resource_type="AWS::S3::Bucket",
            failure_reason="Reason",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
            resource_id="res-123",
        )

        failure2 = Failure(
            test_id="test-123",
            test_name="Test",
            resource_arn="arn:aws:s3:::bucket2",  # Different ARN
            resource_type="AWS::S3::Bucket",
            failure_reason="Reason",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
            resource_id="res-456",
        )

        hash1 = client.generate_failure_hash(failure1)
        hash2 = client.generate_failure_hash(failure2)

        assert hash1 != hash2


class TestVantaClientGetFailingTestsSince:
    """Tests for VantaClient.get_failing_tests_since convenience method."""

    @responses.activate
    def test_get_failing_tests_since_with_timestamp(
        self,
        sample_vanta_api_response: dict[str, object],
    ) -> None:
        """Test get_failing_tests_since with a timestamp."""
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json=sample_vanta_api_response,
            status=200,
        )

        client = VantaClient(api_token="test_token")
        last_check = datetime.now(UTC) - timedelta(hours=1)

        failures = client.get_failing_tests_since(last_check)

        assert isinstance(failures, list)

    @responses.activate
    def test_get_failing_tests_since_none_returns_all(
        self,
        sample_vanta_api_response: dict[str, object],
    ) -> None:
        """Test that None timestamp returns all failures."""
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/tests",
            json=sample_vanta_api_response,
            status=200,
        )

        client = VantaClient(api_token="test_token")

        failures = client.get_failing_tests_since(None)

        assert len(failures) == 1


class TestVantaClientEnrichFailure:
    """Tests for VantaClient._enrich_failure method."""

    @responses.activate
    def test_enrich_failure_with_resource_id(self) -> None:
        """Test failure enrichment when resource_id is present."""
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/resources/res-123",
            json={
                "id": "res-123",
                "name": "test-resource",
                "metadata": {"key": "value"},
            },
            status=200,
        )

        client = VantaClient(api_token="test_token")

        failure_data = {
            "test_id": "test-123",
            "resource_id": "res-123",
        }

        enriched = client._enrich_failure(failure_data)  # pyright: ignore[reportPrivateUsage]

        assert "resource_details" in enriched
        assert enriched["resource_details"]["name"] == "test-resource"

    @responses.activate
    def test_enrich_failure_without_resource_id(self) -> None:
        """Test that enrichment is skipped without resource_id."""
        client = VantaClient(api_token="test_token")

        failure_data = {
            "test_id": "test-123",
        }

        enriched = client._enrich_failure(failure_data)  # pyright: ignore[reportPrivateUsage]

        # Should return unchanged
        assert enriched == failure_data

    @responses.activate
    def test_enrich_failure_handles_404(self) -> None:
        """Test graceful handling of 404 during enrichment."""
        _ = responses.add(
            responses.GET,
            "https://api.vanta.com/v1/resources/res-missing",
            json={"error": "Not found"},
            status=404,
        )

        client = VantaClient(api_token="test_token")

        failure_data = {
            "test_id": "test-123",
            "resource_id": "res-missing",
        }

        # Should not raise, just skip enrichment
        enriched = client._enrich_failure(failure_data)  # pyright: ignore[reportPrivateUsage]

        assert "resource_details" not in enriched


class TestVantaClientParseTimestamp:
    """Tests for VantaClient._parse_timestamp method."""

    @responses.activate
    def test_parse_timestamp_iso8601(self) -> None:
        """Test parsing standard ISO 8601 timestamp."""
        client = VantaClient(api_token="test_token")

        result = client._parse_timestamp("2025-01-15T10:30:00+00:00")  # pyright: ignore[reportPrivateUsage]

        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    @responses.activate
    def test_parse_timestamp_with_z_suffix(self) -> None:
        """Test parsing timestamp with Z suffix."""
        client = VantaClient(api_token="test_token")

        result = client._parse_timestamp("2025-01-15T10:30:00Z")  # pyright: ignore[reportPrivateUsage]

        assert result.year == 2025
        assert result.hour == 10

    @responses.activate
    def test_parse_timestamp_invalid_returns_min(self) -> None:
        """Test that invalid timestamp returns datetime.min."""
        client = VantaClient(api_token="test_token")

        result = client._parse_timestamp("invalid-timestamp")  # pyright: ignore[reportPrivateUsage]

        assert result == datetime.min

    @responses.activate
    def test_parse_timestamp_empty_returns_min(self) -> None:
        """Test that empty string returns datetime.min."""
        client = VantaClient(api_token="test_token")

        result = client._parse_timestamp("")  # pyright: ignore[reportPrivateUsage]

        assert result == datetime.min

