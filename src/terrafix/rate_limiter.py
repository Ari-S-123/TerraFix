"""
Rate limiter for API call throttling.

Implements a token bucket algorithm for controlling request rates to
external APIs. This prevents HTTP 429 (Too Many Requests) errors and
ensures compliance with API rate limits.

The Vanta API enforces the following limits:
- Management endpoints: 50 requests/minute
- Integration endpoints: 20 requests/minute

Usage:
    from terrafix.rate_limiter import TokenBucketRateLimiter, RateLimitConfig

    limiter = TokenBucketRateLimiter(
        RateLimitConfig(requests_per_minute=50, burst_size=10)
    )

    # Before each API call:
    if limiter.acquire(timeout=60.0):
        response = api.call()
    else:
        raise RateLimitError("Timeout waiting for rate limit")
"""

import threading
import time
from dataclasses import dataclass

from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


@dataclass
class RateLimitConfig:
    """
    Configuration for rate limiting.

    Attributes:
        requests_per_minute: Maximum requests allowed per minute
        burst_size: Maximum burst size (tokens available at once).
            This allows short bursts of requests while still enforcing
            the overall rate limit over time.
    """

    requests_per_minute: int
    burst_size: int = 10


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter for API call throttling.

    Tokens are added at a fixed rate up to a maximum bucket size.
    Each API call consumes one token. If no tokens are available,
    the caller blocks until a token becomes available or timeout
    is reached.

    The token bucket algorithm allows short bursts of requests (up to
    burst_size) while enforcing the average rate limit over time.

    Thread-safe implementation using locks.

    Attributes:
        rate: Tokens added per second
        capacity: Maximum tokens in bucket (burst size)
        tokens: Current token count (float for precision)
    """

    def __init__(self, config: RateLimitConfig) -> None:
        """
        Initialize rate limiter with configuration.

        Args:
            config: Rate limit configuration specifying requests/minute
                and burst size

        Example:
            >>> limiter = TokenBucketRateLimiter(
            ...     RateLimitConfig(requests_per_minute=50, burst_size=10)
            ... )
        """
        self.rate: float = config.requests_per_minute / 60.0  # tokens per second
        self.capacity: float = float(config.burst_size)
        self.tokens: float = float(config.burst_size)  # Start with full bucket
        self.last_update: float = time.monotonic()
        self._lock: threading.Lock = threading.Lock()

        log_with_context(
            logger,
            "debug",
            "Initialized rate limiter",
            requests_per_minute=config.requests_per_minute,
            burst_size=config.burst_size,
            tokens_per_second=self.rate,
        )

    def acquire(self, timeout: float = 60.0) -> bool:
        """
        Acquire a token, blocking if necessary until one is available.

        This method is thread-safe and will block the calling thread
        if no tokens are available. It will wait up to the specified
        timeout for a token to become available.

        Args:
            timeout: Maximum seconds to wait for a token. If 0, returns
                immediately without waiting.

        Returns:
            True if a token was acquired within the timeout
            False if timeout was exceeded without acquiring a token

        Example:
            >>> if limiter.acquire(timeout=30.0):
            ...     # Token acquired, safe to make API call
            ...     response = api.call()
            ... else:
            ...     # Timeout - handle rate limit exceeded
            ...     raise RateLimitError("Rate limit timeout")
        """
        deadline = time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True

                # Calculate wait time for next token
                wait_time = (1.0 - self.tokens) / self.rate

            # Check if waiting would exceed deadline
            if time.monotonic() + wait_time > deadline:
                log_with_context(
                    logger,
                    "warning",
                    "Rate limit acquire timeout",
                    timeout=timeout,
                    wait_time=wait_time,
                )
                return False

            # Sleep in small increments for responsiveness
            # This allows cancellation and reduces lock contention
            sleep_duration = min(wait_time, 0.1)
            time.sleep(sleep_duration)

    def try_acquire(self) -> bool:
        """
        Try to acquire a token without blocking.

        This is a non-blocking alternative to acquire() that returns
        immediately if no token is available.

        Returns:
            True if a token was acquired, False otherwise

        Example:
            >>> if limiter.try_acquire():
            ...     response = api.call()
            ... else:
            ...     # No token available, try again later
            ...     pass
        """
        with self._lock:
            self._refill()

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

    def _refill(self) -> None:
        """
        Add tokens based on elapsed time since last update.

        Must be called while holding the lock.
        """
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

    def get_available_tokens(self) -> float:
        """
        Get the current number of available tokens.

        Useful for monitoring and debugging.

        Returns:
            Number of tokens currently available (may be fractional)
        """
        with self._lock:
            self._refill()
            return self.tokens

    def get_wait_time(self) -> float:
        """
        Estimate wait time until a token is available.

        Returns:
            Estimated seconds until a token is available (0 if available now)
        """
        with self._lock:
            self._refill()
            if self.tokens >= 1.0:
                return 0.0
            return (1.0 - self.tokens) / self.rate


# Pre-configured rate limiters for Vanta API endpoints
# These are module-level singletons shared across all VantaClient instances

VANTA_MANAGEMENT_LIMITER = TokenBucketRateLimiter(
    RateLimitConfig(requests_per_minute=50, burst_size=10)
)
"""
Rate limiter for Vanta management API endpoints.

Limit: 50 requests per minute with burst of 10.
Use this for endpoints like /v1/tests, /v1/resources.
"""

VANTA_INTEGRATION_LIMITER = TokenBucketRateLimiter(
    RateLimitConfig(requests_per_minute=20, burst_size=5)
)
"""
Rate limiter for Vanta integration API endpoints.

Limit: 20 requests per minute with burst of 5.
Use this for integration-specific endpoints.
"""
