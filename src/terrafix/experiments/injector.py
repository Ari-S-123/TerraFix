"""
Failure injector for TerraFix resilience testing.

This module provides controlled failure injection for testing
the error handling and retry logic of the TerraFix pipeline.
It can simulate various failure modes in external service calls.

Supported failure modes:
    - Bedrock throttling (HTTP 429)
    - GitHub rate limiting (HTTP 403)
    - Git clone timeouts
    - Redis connection failures
    - Transient network errors

Usage:
    from terrafix.experiments.injector import FailureInjector

    injector = FailureInjector(failure_rate=0.1)  # 10% failure rate

    # Use with patching
    with injector.inject_bedrock_throttling():
        # Bedrock calls may fail with throttling errors
        pass
"""

import random
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError


class FailureInjector:
    """
    Controlled failure injection for resilience testing.

    Provides context managers that inject failures into service calls
    at a configurable rate, enabling testing of error handling and
    retry logic.

    Attributes:
        failure_rate: Probability of failure (0.0 to 1.0)
        seed: Random seed for reproducible failures

    Example:
        >>> injector = FailureInjector(failure_rate=0.2)
        >>> with injector.inject_bedrock_throttling():
        ...     response = bedrock.invoke_model(...)  # May fail 20% of time
    """

    def __init__(
        self,
        failure_rate: float = 0.1,
        seed: int | None = None,
    ) -> None:
        """
        Initialize the failure injector.

        Args:
            failure_rate: Probability of injecting a failure (0.0 to 1.0)
            seed: Optional random seed for reproducible behavior
        """
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be between 0.0 and 1.0")

        self.failure_rate = failure_rate
        self._random = random.Random(seed)
        self._injection_count = 0
        self._failure_count = 0

    def _should_fail(self) -> bool:
        """Determine if this call should fail based on failure rate."""
        self._injection_count += 1
        should_fail = self._random.random() < self.failure_rate
        if should_fail:
            self._failure_count += 1
        return should_fail

    def get_stats(self) -> dict[str, Any]:
        """
        Get injection statistics.

        Returns:
            Dictionary with injection counts and failure rate
        """
        actual_rate = (
            self._failure_count / self._injection_count if self._injection_count > 0 else 0.0
        )
        return {
            "total_injections": self._injection_count,
            "failures_injected": self._failure_count,
            "configured_rate": self.failure_rate,
            "actual_rate": actual_rate,
        }

    def reset_stats(self) -> None:
        """Reset injection statistics."""
        self._injection_count = 0
        self._failure_count = 0

    @contextmanager
    def inject_bedrock_throttling(self) -> Generator[None, None, None]:
        """
        Inject Bedrock throttling errors.

        Creates a context where Bedrock invoke_model calls may fail
        with ThrottlingException errors at the configured rate.

        Yields:
            None (context manager)

        Example:
            >>> with injector.inject_bedrock_throttling():
            ...     # This may raise ThrottlingException
            ...     response = bedrock.invoke_model(...)
        """
        original_method = None

        def throttled_invoke(*args: Any, **kwargs: Any) -> Any:
            if self._should_fail():
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ThrottlingException",
                            "Message": "Rate exceeded [injected failure]",
                        }
                    },
                    "InvokeModel",
                )
            if original_method:
                return original_method(*args, **kwargs)
            return MagicMock()

        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            original_method = mock_client.invoke_model
            mock_client.invoke_model.side_effect = throttled_invoke
            mock_boto.return_value = mock_client
            yield

    @contextmanager
    def inject_github_rate_limit(self) -> Generator[None, None, None]:
        """
        Inject GitHub API rate limiting errors.

        Creates a context where GitHub API calls may fail with
        rate limit errors at the configured rate.

        Yields:
            None (context manager)

        Example:
            >>> with injector.inject_github_rate_limit():
            ...     repo.create_pull(...)  # May fail with rate limit
        """
        from github import RateLimitExceededException

        def rate_limited_call(*args: Any, **kwargs: Any) -> Any:
            if self._should_fail():
                raise RateLimitExceededException(
                    status=403,
                    data={"message": "API rate limit exceeded [injected failure]"},
                    headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
                )
            return MagicMock()

        with patch("github.Github") as mock_github:
            mock_instance = MagicMock()
            mock_repo = MagicMock()
            mock_repo.create_pull.side_effect = rate_limited_call
            mock_repo.get_contents.side_effect = rate_limited_call
            mock_repo.update_file.side_effect = rate_limited_call
            mock_instance.get_repo.return_value = mock_repo
            mock_github.return_value = mock_instance
            yield

    @contextmanager
    def inject_git_timeout(self) -> Generator[None, None, None]:
        """
        Inject Git clone timeout errors.

        Creates a context where Git clone operations may fail
        with timeout errors at the configured rate.

        Yields:
            None (context manager)
        """
        import subprocess

        def timeout_clone(*args: Any, **kwargs: Any) -> Any:
            if self._should_fail():
                raise subprocess.TimeoutExpired(
                    cmd="git clone",
                    timeout=30,
                )
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

        with patch("subprocess.run", side_effect=timeout_clone):
            yield

    @contextmanager
    def inject_redis_failure(self) -> Generator[None, None, None]:
        """
        Inject Redis connection failures.

        Creates a context where Redis operations may fail
        with connection errors at the configured rate.

        Yields:
            None (context manager)
        """
        from redis import ConnectionError as RedisConnectionError

        def redis_failure(*args: Any, **kwargs: Any) -> Any:
            if self._should_fail():
                raise RedisConnectionError("Connection refused [injected failure]")
            return MagicMock()

        with patch("redis.from_url") as mock_redis:
            mock_client = MagicMock()
            mock_client.get.side_effect = redis_failure
            mock_client.set.side_effect = redis_failure
            mock_client.setnx.side_effect = redis_failure
            mock_redis.return_value = mock_client
            yield

    @contextmanager
    def inject_network_error(self) -> Generator[None, None, None]:
        """
        Inject generic network errors.

        Creates a context where HTTP requests may fail
        with connection errors at the configured rate.

        Yields:
            None (context manager)
        """
        import requests

        original_request = requests.Session.request

        def network_error(self_session: Any, method: str, url: str, **kwargs: Any) -> Any:
            if self._should_fail():
                raise requests.exceptions.ConnectionError(
                    f"Failed to establish connection to {url} [injected failure]"
                )
            return original_request(self_session, method, url, **kwargs)

        with patch.object(requests.Session, "request", network_error):
            yield

    @contextmanager
    def inject_all_failures(self) -> Generator[None, None, None]:
        """
        Inject all failure types simultaneously.

        Useful for comprehensive resilience testing where any
        external call might fail.

        Yields:
            None (context manager)

        Example:
            >>> with injector.inject_all_failures():
            ...     # Any external call may fail
            ...     await process_failure(failure)
        """
        with (
            self.inject_bedrock_throttling(),
            self.inject_github_rate_limit(),
            self.inject_git_timeout(),
            self.inject_redis_failure(),
            self.inject_network_error(),
        ):
            yield

