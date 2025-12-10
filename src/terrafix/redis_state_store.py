"""
Redis-backed state store for failure deduplication.

Provides atomic operations for tracking processed failures with
automatic TTL-based expiration. Uses Redis SET NX for race-free
deduplication checks, preventing duplicate PR creation when multiple
workers process failures concurrently.

This module replaces the SQLite-based StateStore for production
deployments on ECS/Fargate where ephemeral storage causes state loss
on task restart.

Usage:
    from terrafix.redis_state_store import RedisStateStore

    store = RedisStateStore(redis_url="redis://localhost:6379/0")
    
    if store.check_and_claim(failure_hash):
        # Process failure...
        store.mark_completed(failure_hash, pr_url)
    else:
        # Already claimed by another worker
        pass
"""

import json
from datetime import datetime
from enum import Enum
from typing import Any

import redis
from redis.exceptions import RedisError

from terrafix.errors import StateStoreError
from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


class FailureStatus(str, Enum):
    """
    Status of a failure in the processing pipeline.

    Attributes:
        PENDING: Failure detected but not yet claimed for processing
        IN_PROGRESS: Currently being processed by a worker
        COMPLETED: Successfully processed with PR created
        FAILED: Processing failed permanently
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RedisStateStore:
    """
    Redis-backed state store for tracking processed failures.

    Uses Redis SET NX operations for atomic deduplication checks,
    preventing race conditions when multiple workers process
    failures concurrently. Records automatically expire after
    the configured TTL.

    Attributes:
        client: Redis client instance with connection pooling
        key_prefix: Prefix for all keys to namespace TerraFix data
        ttl_seconds: Time-to-live for state records in seconds
    """

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "terrafix:",
        ttl_days: int = 7,
    ) -> None:
        """
        Initialize Redis state store.

        Creates a Redis client with connection pooling and verifies
        connectivity with a PING command.

        Args:
            redis_url: Redis connection URL (redis://host:port/db)
            key_prefix: Prefix for all Redis keys to namespace data
            ttl_days: Number of days to retain state records before expiration

        Raises:
            StateStoreError: If Redis connection fails

        Example:
            >>> store = RedisStateStore("redis://localhost:6379/0")
            >>> store.check_and_claim("abc123")
            True
        """
        try:
            self.client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            # Verify connection
            self.client.ping()

            log_with_context(
                logger,
                "info",
                "Connected to Redis",
                redis_url=self._sanitize_url(redis_url),
            )

        except RedisError as e:
            log_with_context(
                logger,
                "error",
                "Failed to connect to Redis",
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to connect to Redis: {e}",
                operation="connect",
            ) from e

        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_days * 24 * 60 * 60

    def _sanitize_url(self, url: str) -> str:
        """
        Remove credentials from Redis URL for logging.

        Args:
            url: Redis connection URL

        Returns:
            URL with password redacted
        """
        # Simple redaction - replace password if present
        if "@" in url:
            # Format: redis://user:password@host:port/db
            parts = url.split("@")
            return f"redis://***@{parts[-1]}"
        return url

    def _make_key(self, failure_hash: str) -> str:
        """
        Generate namespaced Redis key for a failure hash.

        Args:
            failure_hash: SHA256 hash of failure signature

        Returns:
            Fully qualified Redis key
        """
        return f"{self.key_prefix}failure:{failure_hash}"

    def check_and_claim(self, failure_hash: str) -> bool:
        """
        Atomically check if failure is new and claim it for processing.

        This uses Redis SET NX (set if not exists) to provide atomic
        check-and-set semantics, preventing race conditions when
        multiple workers encounter the same failure simultaneously.

        Args:
            failure_hash: SHA256 hash of the failure signature

        Returns:
            True if this worker claimed the failure (proceed with processing)
            False if failure was already claimed (skip processing)

        Raises:
            StateStoreError: If Redis operation fails

        Example:
            >>> if store.check_and_claim(failure_hash):
            ...     # This worker owns the failure
            ...     process_failure()
            ... else:
            ...     # Another worker is handling it
            ...     pass
        """
        key = self._make_key(failure_hash)
        record = json.dumps({
            "status": FailureStatus.IN_PROGRESS.value,
            "claimed_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })

        try:
            # SET NX returns True only if key didn't exist
            claimed = self.client.set(key, record, nx=True, ex=self.ttl_seconds)
            result = bool(claimed)

            log_with_context(
                logger,
                "debug",
                "Attempted to claim failure",
                failure_hash=failure_hash[:16],
                claimed=result,
            )

            return result

        except RedisError as e:
            log_with_context(
                logger,
                "error",
                "Failed to claim failure",
                failure_hash=failure_hash[:16],
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to claim failure: {e}",
                operation="check_and_claim",
            ) from e

    def is_already_processed(self, failure_hash: str) -> bool:
        """
        Check if failure has already been processed or is being processed.

        This is a read-only check that does not claim the failure.
        Use check_and_claim() for atomic claim operations.

        Args:
            failure_hash: SHA256 hash of failure signature

        Returns:
            True if failure exists in store (any status except FAILED)

        Raises:
            StateStoreError: If Redis query fails

        Example:
            >>> if store.is_already_processed(failure_hash):
            ...     print("Already handled")
        """
        key = self._make_key(failure_hash)

        try:
            data = self.client.get(key)
            if data is None:
                return False

            record = json.loads(data)
            status = record.get("status")

            # Consider IN_PROGRESS and COMPLETED as already processed
            # FAILED can be retried
            already_processed = status in [
                FailureStatus.IN_PROGRESS.value,
                FailureStatus.COMPLETED.value,
            ]

            log_with_context(
                logger,
                "debug",
                "Checked processing status",
                failure_hash=failure_hash[:16],
                status=status,
                already_processed=already_processed,
            )

            return already_processed

        except RedisError as e:
            log_with_context(
                logger,
                "error",
                "Failed to check processing status",
                failure_hash=failure_hash[:16],
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to check processing status: {e}",
                operation="is_already_processed",
            ) from e

    def mark_in_progress(
        self,
        failure_hash: str,
        test_id: str,
        resource_arn: str,
    ) -> None:
        """
        Mark failure as currently being processed.

        Updates an existing record or creates a new one with IN_PROGRESS
        status. This is typically called after check_and_claim() succeeds
        to add metadata.

        Args:
            failure_hash: SHA256 hash of failure signature
            test_id: Vanta test ID for tracking
            resource_arn: AWS resource ARN being processed

        Raises:
            StateStoreError: If Redis update fails

        Example:
            >>> store.mark_in_progress(hash, "test-123", "arn:aws:s3:::bucket")
        """
        key = self._make_key(failure_hash)
        record = json.dumps({
            "status": FailureStatus.IN_PROGRESS.value,
            "test_id": test_id,
            "resource_arn": resource_arn,
            "claimed_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })

        try:
            self.client.set(key, record, ex=self.ttl_seconds)

            log_with_context(
                logger,
                "info",
                "Marked failure as in progress",
                failure_hash=failure_hash[:16],
                test_id=test_id,
            )

        except RedisError as e:
            log_with_context(
                logger,
                "error",
                "Failed to mark in progress",
                failure_hash=failure_hash[:16],
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to mark in progress: {e}",
                operation="mark_in_progress",
            ) from e

    def mark_processed(
        self,
        failure_hash: str,
        pr_url: str,
    ) -> None:
        """
        Mark failure as successfully processed.

        Updates the record with COMPLETED status and the PR URL.
        The TTL is refreshed to retain the record for the full
        retention period from completion.

        Args:
            failure_hash: SHA256 hash of failure signature
            pr_url: GitHub Pull Request URL

        Raises:
            StateStoreError: If Redis update fails

        Example:
            >>> store.mark_processed(hash, "https://github.com/org/repo/pull/123")
        """
        key = self._make_key(failure_hash)

        try:
            # Get existing record to preserve metadata
            existing = self.client.get(key)
            existing_data = json.loads(existing) if existing else {}

            record = json.dumps({
                **existing_data,
                "status": FailureStatus.COMPLETED.value,
                "pr_url": pr_url,
                "completed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "last_error": None,
            })

            self.client.set(key, record, ex=self.ttl_seconds)

            log_with_context(
                logger,
                "info",
                "Marked failure as completed",
                failure_hash=failure_hash[:16],
                pr_url=pr_url,
            )

        except RedisError as e:
            log_with_context(
                logger,
                "error",
                "Failed to mark processed",
                failure_hash=failure_hash[:16],
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to mark processed: {e}",
                operation="mark_processed",
            ) from e

    def mark_failed(
        self,
        failure_hash: str,
        error: str,
    ) -> None:
        """
        Mark failure as permanently failed.

        Updates the record with FAILED status and error message.
        Failed records can be retried on subsequent polling cycles.

        Args:
            failure_hash: SHA256 hash of failure signature
            error: Error message describing the failure

        Raises:
            StateStoreError: If Redis update fails

        Example:
            >>> store.mark_failed(hash, "Resource not found in Terraform")
        """
        key = self._make_key(failure_hash)

        try:
            # Get existing record to preserve metadata
            existing = self.client.get(key)
            existing_data = json.loads(existing) if existing else {}

            # Truncate error message to prevent excessive storage
            truncated_error = error[:1000] if error else "Unknown error"

            record = json.dumps({
                **existing_data,
                "status": FailureStatus.FAILED.value,
                "last_error": truncated_error,
                "failed_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            })

            self.client.set(key, record, ex=self.ttl_seconds)

            log_with_context(
                logger,
                "info",
                "Marked failure as failed",
                failure_hash=failure_hash[:16],
                error=truncated_error[:200],
            )

        except RedisError as e:
            log_with_context(
                logger,
                "error",
                "Failed to mark as failed",
                failure_hash=failure_hash[:16],
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to mark as failed: {e}",
                operation="mark_failed",
            ) from e

    def get_status(self, failure_hash: str) -> FailureStatus | None:
        """
        Get current status of a failure.

        Args:
            failure_hash: SHA256 hash of failure signature

        Returns:
            Current FailureStatus or None if not found

        Raises:
            StateStoreError: If Redis query fails

        Example:
            >>> status = store.get_status(failure_hash)
            >>> if status == FailureStatus.COMPLETED:
            ...     print("Already done")
        """
        key = self._make_key(failure_hash)

        try:
            data = self.client.get(key)
            if data is None:
                return None

            record = json.loads(data)
            return FailureStatus(record["status"])

        except RedisError as e:
            log_with_context(
                logger,
                "error",
                "Failed to get status",
                failure_hash=failure_hash[:16],
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to get status: {e}",
                operation="get_status",
            ) from e

    def get_statistics(self) -> dict[str, Any]:
        """
        Get aggregate statistics about processed failures.

        Scans all failure keys and aggregates counts by status.
        This operation may be slow with large datasets.

        Returns:
            Dictionary with counts by status and total

        Raises:
            StateStoreError: If Redis scan fails

        Example:
            >>> stats = store.get_statistics()
            >>> print(f"Completed: {stats['completed']}")
        """
        pattern = f"{self.key_prefix}failure:*"
        stats: dict[str, int] = {status.value: 0 for status in FailureStatus}
        stats["total"] = 0

        try:
            cursor = 0
            while True:
                cursor, keys = self.client.scan(cursor, match=pattern, count=100)

                for key in keys:
                    data = self.client.get(key)
                    if data:
                        record = json.loads(data)
                        status = record.get("status", "unknown")
                        if status in stats:
                            stats[status] += 1
                        stats["total"] += 1

                if cursor == 0:
                    break

            log_with_context(
                logger,
                "debug",
                "Retrieved statistics",
                stats=stats,
            )

            return stats

        except RedisError as e:
            log_with_context(
                logger,
                "error",
                "Failed to get statistics",
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to get statistics: {e}",
                operation="get_statistics",
            ) from e

    def cleanup_old_records(self, retention_days: int = 7) -> int:
        """
        Cleanup placeholder for API compatibility.

        Redis handles expiration automatically via TTL, so this method
        is a no-op. It exists for compatibility with the StateStore
        interface used by the SQLite implementation.

        Args:
            retention_days: Ignored (TTL is set at record creation)

        Returns:
            Always returns 0 (Redis handles expiration automatically)

        Example:
            >>> deleted = store.cleanup_old_records()  # No-op
        """
        log_with_context(
            logger,
            "debug",
            "Cleanup not needed - Redis TTL handles expiration",
            retention_days=retention_days,
        )
        return 0

    def close(self) -> None:
        """
        Close Redis connection.

        Releases the connection back to the pool. Safe to call
        multiple times.

        Example:
            >>> store.close()
        """
        try:
            self.client.close()
            log_with_context(
                logger,
                "debug",
                "Closed Redis connection",
            )
        except RedisError as e:
            log_with_context(
                logger,
                "warning",
                "Error closing Redis connection",
                error=str(e),
            )

    def __enter__(self) -> "RedisStateStore":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

