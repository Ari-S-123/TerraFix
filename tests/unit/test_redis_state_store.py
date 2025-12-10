"""
Unit tests for RedisStateStore.

Tests cover state operations, deduplication, status tracking,
and error handling using fakeredis.
"""

from unittest.mock import MagicMock

import pytest

from terrafix.redis_state_store import FailureStatus, RedisStateStore


class TestRedisStateStoreInit:
    """Tests for RedisStateStore initialization."""

    def test_init_with_mock_redis(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test initialization with mocked Redis."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        assert store.key_prefix == "terrafix:"
        assert store.ttl_seconds == 7 * 24 * 60 * 60  # 7 days

    def test_init_with_custom_prefix(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test initialization with custom key prefix."""
        store = RedisStateStore(
            redis_url="redis://localhost:6379/0",
            key_prefix="custom:",
            ttl_days=14,
        )

        assert store.key_prefix == "custom:"
        assert store.ttl_seconds == 14 * 24 * 60 * 60


class TestCheckAndClaim:
    """Tests for RedisStateStore.check_and_claim method."""

    def test_check_and_claim_new_failure(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test claiming a new failure returns True."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        result = store.check_and_claim("new_hash_123")

        assert result is True

    def test_check_and_claim_existing_failure(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test claiming an existing failure returns False."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        # First claim succeeds
        result1 = store.check_and_claim("hash_456")
        assert result1 is True

        # Second claim fails (already claimed)
        result2 = store.check_and_claim("hash_456")
        assert result2 is False


class TestIsAlreadyProcessed:
    """Tests for RedisStateStore.is_already_processed method."""

    def test_not_processed_returns_false(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test that non-existent failure returns False."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        result = store.is_already_processed("nonexistent_hash")

        assert result is False

    def test_in_progress_returns_true(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test that in-progress failure returns True."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        # Claim the failure (sets IN_PROGRESS)
        store.check_and_claim("hash_789")

        result = store.is_already_processed("hash_789")

        assert result is True

    def test_completed_returns_true(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test that completed failure returns True."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        # Claim and complete
        store.check_and_claim("hash_completed")
        store.mark_processed("hash_completed", "https://github.com/pull/1")

        result = store.is_already_processed("hash_completed")

        assert result is True


class TestMarkInProgress:
    """Tests for RedisStateStore.mark_in_progress method."""

    def test_mark_in_progress_sets_status(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test marking failure as in progress."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        store.mark_in_progress(
            failure_hash="hash_progress",
            test_id="test-123",
            resource_arn="arn:aws:s3:::bucket",
        )

        status = store.get_status("hash_progress")
        assert status == FailureStatus.IN_PROGRESS


class TestMarkProcessed:
    """Tests for RedisStateStore.mark_processed method."""

    def test_mark_processed_sets_completed(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test marking failure as completed."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        store.check_and_claim("hash_complete")
        store.mark_processed("hash_complete", "https://github.com/pull/42")

        status = store.get_status("hash_complete")
        assert status == FailureStatus.COMPLETED


class TestMarkFailed:
    """Tests for RedisStateStore.mark_failed method."""

    def test_mark_failed_sets_status(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test marking failure as failed."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        store.check_and_claim("hash_failed")
        store.mark_failed("hash_failed", "Processing error occurred")

        status = store.get_status("hash_failed")
        assert status == FailureStatus.FAILED


class TestGetStatus:
    """Tests for RedisStateStore.get_status method."""

    def test_get_status_nonexistent(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test getting status of non-existent failure."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        status = store.get_status("nonexistent")

        assert status is None

    def test_get_status_returns_correct_enum(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test that get_status returns correct FailureStatus enum."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        store.check_and_claim("hash_enum")
        status = store.get_status("hash_enum")

        assert isinstance(status, FailureStatus)
        assert status == FailureStatus.IN_PROGRESS


class TestGetStatistics:
    """Tests for RedisStateStore.get_statistics method."""

    def test_get_statistics_empty_store(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test statistics on empty store."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        stats = store.get_statistics()

        assert stats["total"] == 0
        assert stats["in_progress"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0

    def test_get_statistics_with_records(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test statistics with some records."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        # Create some records
        store.check_and_claim("hash_1")  # IN_PROGRESS
        store.check_and_claim("hash_2")  # IN_PROGRESS
        store.mark_processed("hash_1", "url")  # Now COMPLETED

        stats = store.get_statistics()

        assert stats["total"] >= 2
        assert stats["completed"] >= 1


class TestCleanupOldRecords:
    """Tests for RedisStateStore.cleanup_old_records method."""

    def test_cleanup_is_noop(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test that cleanup is a no-op (Redis TTL handles expiration)."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        deleted = store.cleanup_old_records(retention_days=7)

        assert deleted == 0


class TestContextManager:
    """Tests for RedisStateStore context manager."""

    def test_context_manager_closes_connection(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test that context manager closes connection."""
        with RedisStateStore(redis_url="redis://localhost:6379/0") as store:
            store.check_and_claim("hash_context")

        # Connection should be closed (no exception means success)


class TestSanitizeUrl:
    """Tests for RedisStateStore._sanitize_url method."""

    def test_sanitize_url_with_password(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test URL sanitization removes password."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        sanitized = store._sanitize_url("redis://user:secret123@localhost:6379/0")

        assert "secret123" not in sanitized
        assert "***" in sanitized

    def test_sanitize_url_without_password(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test URL without password is unchanged."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")

        sanitized = store._sanitize_url("redis://localhost:6379/0")

        assert sanitized == "redis://localhost:6379/0"


class TestMakeKey:
    """Tests for RedisStateStore._make_key method."""

    def test_make_key_format(
        self,
        mock_redis_client: MagicMock,
    ) -> None:
        """Test key generation format."""
        store = RedisStateStore(
            redis_url="redis://localhost:6379/0",
            key_prefix="test:",
        )

        key = store._make_key("abc123")

        assert key == "test:failure:abc123"

