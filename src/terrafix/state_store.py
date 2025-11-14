"""
SQLite-based state store for tracking processed failures.

This module provides a persistent deduplication layer to avoid processing
the same compliance failure multiple times. It stores failure hashes,
processing status, and PR URLs in a local SQLite database.

The state store is designed for single-task ECS deployment where SQLite
state is ephemeral per task. For persistent state across task restarts,
mount an EFS volume.

Usage:
    from terrafix.state_store import StateStore

    store = StateStore(db_path="./terrafix.db")
    store.initialize_schema()

    if not store.is_already_processed(failure_hash):
        store.mark_in_progress(failure_hash, test_id, resource_arn)
        # ... process failure ...
        store.mark_processed(failure_hash, pr_url)
"""

import sqlite3
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from terrafix.errors import StateStoreError
from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


class ProcessingStatus(str, Enum):
    """
    Processing status for failures.

    Attributes:
        PENDING: Failure detected but not yet processed
        IN_PROGRESS: Currently being processed
        COMPLETED: Successfully processed with PR created
        FAILED: Processing failed permanently
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class StateStore:
    """
    SQLite-based state store for processed failures.

    Manages a SQLite database tracking which compliance failures have
    been processed to avoid duplicate PR creation. Thread-safe for
    single-process use via connection serialization.

    Attributes:
        db_path: Path to SQLite database file
        conn: SQLite connection (one per process)
    """

    def __init__(self, db_path: str = "./terrafix.db") -> None:
        """
        Initialize state store.

        Args:
            db_path: Path to SQLite database file

        Example:
            >>> store = StateStore("./terrafix.db")
            >>> store.initialize_schema()
        """
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None

        log_with_context(
            logger,
            "info",
            "Initialized state store",
            db_path=str(self.db_path),
        )

    def initialize_schema(self) -> None:
        """
        Initialize database schema.

        Creates the processed_failures table if it doesn't exist.
        Safe to call multiple times (idempotent).

        Raises:
            StateStoreError: If schema creation fails
        """
        self._ensure_connection()

        try:
            cursor = self.conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_failures (
                    failure_hash TEXT PRIMARY KEY,
                    test_id TEXT NOT NULL,
                    resource_arn TEXT NOT NULL,
                    status TEXT NOT NULL,
                    first_seen TIMESTAMP NOT NULL,
                    last_processed TIMESTAMP,
                    pr_url TEXT,
                    last_error TEXT
                )
            """)

            # Create index for efficient querying by status
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status
                ON processed_failures(status)
            """)

            # Create index for cleanup queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_last_processed
                ON processed_failures(last_processed)
            """)

            self.conn.commit()

            log_with_context(
                logger,
                "info",
                "Initialized database schema",
            )

        except sqlite3.Error as e:
            log_with_context(
                logger,
                "error",
                "Failed to initialize schema",
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to initialize schema: {e}",
                operation="initialize_schema",
                sqlite_error=str(e),
            ) from e

    def is_already_processed(self, failure_hash: str) -> bool:
        """
        Check if failure has already been processed.

        Args:
            failure_hash: SHA256 hash of failure signature

        Returns:
            True if failure has been processed (completed or in progress)

        Raises:
            StateStoreError: If database query fails

        Example:
            >>> if not store.is_already_processed(hash):
            ...     process_failure()
        """
        self._ensure_connection()

        try:
            cursor = self.conn.cursor()

            cursor.execute(
                """
                SELECT status FROM processed_failures
                WHERE failure_hash = ?
                """,
                (failure_hash,),
            )

            row = cursor.fetchone()

            if row is None:
                return False

            status = row[0]
            # Consider in_progress and completed as already processed
            already_processed = status in [
                ProcessingStatus.IN_PROGRESS.value,
                ProcessingStatus.COMPLETED.value,
            ]

            log_with_context(
                logger,
                "debug",
                "Checked processing status",
                failure_hash=failure_hash,
                status=status,
                already_processed=already_processed,
            )

            return already_processed

        except sqlite3.Error as e:
            log_with_context(
                logger,
                "error",
                "Failed to check processing status",
                failure_hash=failure_hash,
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to check processing status: {e}",
                operation="is_already_processed",
                sqlite_error=str(e),
            ) from e

    def mark_in_progress(
        self,
        failure_hash: str,
        test_id: str,
        resource_arn: str,
    ) -> None:
        """
        Mark failure as currently being processed.

        Args:
            failure_hash: SHA256 hash of failure signature
            test_id: Vanta test ID
            resource_arn: AWS resource ARN

        Raises:
            StateStoreError: If database update fails

        Example:
            >>> store.mark_in_progress(hash, test_id, arn)
        """
        self._ensure_connection()

        try:
            cursor = self.conn.cursor()
            now = datetime.utcnow()

            cursor.execute(
                """
                INSERT OR REPLACE INTO processed_failures
                (failure_hash, test_id, resource_arn, status, first_seen, last_processed)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    failure_hash,
                    test_id,
                    resource_arn,
                    ProcessingStatus.IN_PROGRESS.value,
                    now,
                    now,
                ),
            )

            self.conn.commit()

            log_with_context(
                logger,
                "info",
                "Marked failure as in progress",
                failure_hash=failure_hash,
                test_id=test_id,
            )

        except sqlite3.Error as e:
            log_with_context(
                logger,
                "error",
                "Failed to mark in progress",
                failure_hash=failure_hash,
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to mark in progress: {e}",
                operation="mark_in_progress",
                sqlite_error=str(e),
            ) from e

    def mark_processed(
        self,
        failure_hash: str,
        pr_url: str,
    ) -> None:
        """
        Mark failure as successfully processed.

        Args:
            failure_hash: SHA256 hash of failure signature
            pr_url: GitHub Pull Request URL

        Raises:
            StateStoreError: If database update fails

        Example:
            >>> store.mark_processed(hash, "https://github.com/...")
        """
        self._ensure_connection()

        try:
            cursor = self.conn.cursor()
            now = datetime.utcnow()

            cursor.execute(
                """
                UPDATE processed_failures
                SET status = ?, last_processed = ?, pr_url = ?, last_error = NULL
                WHERE failure_hash = ?
                """,
                (
                    ProcessingStatus.COMPLETED.value,
                    now,
                    pr_url,
                    failure_hash,
                ),
            )

            self.conn.commit()

            log_with_context(
                logger,
                "info",
                "Marked failure as completed",
                failure_hash=failure_hash,
                pr_url=pr_url,
            )

        except sqlite3.Error as e:
            log_with_context(
                logger,
                "error",
                "Failed to mark processed",
                failure_hash=failure_hash,
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to mark processed: {e}",
                operation="mark_processed",
                sqlite_error=str(e),
            ) from e

    def mark_failed(
        self,
        failure_hash: str,
        error: str,
    ) -> None:
        """
        Mark failure as permanently failed.

        Args:
            failure_hash: SHA256 hash of failure signature
            error: Error message describing failure

        Raises:
            StateStoreError: If database update fails

        Example:
            >>> store.mark_failed(hash, "Resource not found")
        """
        self._ensure_connection()

        try:
            cursor = self.conn.cursor()
            now = datetime.utcnow()

            # Truncate error message to avoid excessively large values
            truncated_error = error[:1000] if error else "Unknown error"

            cursor.execute(
                """
                UPDATE processed_failures
                SET status = ?, last_processed = ?, last_error = ?
                WHERE failure_hash = ?
                """,
                (
                    ProcessingStatus.FAILED.value,
                    now,
                    truncated_error,
                    failure_hash,
                ),
            )

            self.conn.commit()

            log_with_context(
                logger,
                "info",
                "Marked failure as failed",
                failure_hash=failure_hash,
                error=truncated_error[:200],
            )

        except sqlite3.Error as e:
            log_with_context(
                logger,
                "error",
                "Failed to mark as failed",
                failure_hash=failure_hash,
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to mark as failed: {e}",
                operation="mark_failed",
                sqlite_error=str(e),
            ) from e

    def cleanup_old_records(self, retention_days: int = 7) -> int:
        """
        Delete old processed failure records.

        Removes records older than retention period to prevent unbounded
        database growth.

        Args:
            retention_days: Days to retain records (default: 7)

        Returns:
            Number of records deleted

        Raises:
            StateStoreError: If cleanup fails

        Example:
            >>> deleted = store.cleanup_old_records(7)
            >>> print(f"Deleted {deleted} old records")
        """
        self._ensure_connection()

        try:
            cursor = self.conn.cursor()
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

            cursor.execute(
                """
                DELETE FROM processed_failures
                WHERE last_processed < ?
                """,
                (cutoff_date,),
            )

            deleted_count = cursor.rowcount
            self.conn.commit()

            log_with_context(
                logger,
                "info",
                "Cleaned up old records",
                deleted_count=deleted_count,
                retention_days=retention_days,
            )

            return deleted_count

        except sqlite3.Error as e:
            log_with_context(
                logger,
                "error",
                "Failed to cleanup old records",
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to cleanup old records: {e}",
                operation="cleanup_old_records",
                sqlite_error=str(e),
            ) from e

    def get_statistics(self) -> dict[str, Any]:
        """
        Get processing statistics.

        Returns:
            Dict with counts by status and total records

        Raises:
            StateStoreError: If query fails

        Example:
            >>> stats = store.get_statistics()
            >>> print(f"Completed: {stats['completed']}")
        """
        self._ensure_connection()

        try:
            cursor = self.conn.cursor()

            cursor.execute(
                """
                SELECT status, COUNT(*) FROM processed_failures
                GROUP BY status
                """
            )

            stats = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) FROM processed_failures")
            total = cursor.fetchone()[0]

            stats["total"] = total

            log_with_context(
                logger,
                "debug",
                "Retrieved statistics",
                stats=stats,
            )

            return stats

        except sqlite3.Error as e:
            log_with_context(
                logger,
                "error",
                "Failed to get statistics",
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to get statistics: {e}",
                operation="get_statistics",
                sqlite_error=str(e),
            ) from e

    def _ensure_connection(self) -> None:
        """
        Ensure database connection is open.

        Creates connection if not already open. Connection is reused
        for the lifetime of the StateStore instance.

        Raises:
            StateStoreError: If connection fails
        """
        if self.conn is not None:
            return

        try:
            # Create parent directory if it doesn't exist
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # Allow use across threads
            )

            # Enable WAL mode for better concurrency
            self.conn.execute("PRAGMA journal_mode=WAL")

            log_with_context(
                logger,
                "debug",
                "Opened database connection",
                db_path=str(self.db_path),
            )

        except sqlite3.Error as e:
            log_with_context(
                logger,
                "error",
                "Failed to open database connection",
                db_path=str(self.db_path),
                error=str(e),
            )
            raise StateStoreError(
                f"Failed to open database connection: {e}",
                operation="connect",
                sqlite_error=str(e),
            ) from e

    def close(self) -> None:
        """
        Close database connection.

        Should be called when the state store is no longer needed.
        Safe to call multiple times.

        Example:
            >>> store.close()
        """
        if self.conn is not None:
            try:
                self.conn.close()
                self.conn = None

                log_with_context(
                    logger,
                    "debug",
                    "Closed database connection",
                )

            except sqlite3.Error as e:
                log_with_context(
                    logger,
                    "warning",
                    "Error closing database connection",
                    error=str(e),
                )

    def __enter__(self) -> "StateStore":
        """Context manager entry."""
        self._ensure_connection()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

