"""
Custom exception classes for TerraFix.

This module defines a hierarchy of exceptions used throughout the TerraFix
application to enable precise error handling and categorization. Each exception
class represents a specific failure mode with clear semantics about whether
it should be retried or treated as permanent.

Exception Hierarchy:
    TerraFixError (base)
    ├── VantaApiError (transient API failures)
    ├── TerraformParseError (permanent parsing failures)
    ├── BedrockError (API failures, often transient)
    ├── GitHubError (API failures, may be transient)
    └── StateStoreError (database errors, usually permanent)

Retry Semantics:
    - Transient errors should be retried with exponential backoff
    - Permanent errors should be logged and marked as failed
    - Network/timeout errors are generally transient
    - Validation/syntax errors are generally permanent
"""


class TerraFixError(Exception):
    """
    Base exception for all TerraFix errors.

    All custom exceptions in TerraFix inherit from this class to enable
    catch-all error handling when needed.

    Attributes:
        message: Human-readable error description
        retryable: Whether this error should be retried
        context: Additional context dictionary for structured logging
    """

    def __init__(
        self,
        message: str,
        retryable: bool = False,
        context: dict[str, object] | None = None,
    ) -> None:
        """
        Initialize TerraFix error.

        Args:
            message: Human-readable error description
            retryable: Whether this error should be retried
            context: Additional context for structured logging
        """
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.context = context or {}

    def __str__(self) -> str:
        """Return string representation of error."""
        return self.message


class VantaApiError(TerraFixError):
    """
    Error communicating with Vanta API.

    Raised when Vanta API requests fail. Most API failures are transient
    (timeouts, rate limits, 5xx errors) and should be retried.

    Attributes:
        status_code: HTTP status code from Vanta API
        response_body: Response body for debugging
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
        retryable: bool = True,
    ) -> None:
        """
        Initialize Vanta API error.

        Args:
            message: Human-readable error description
            status_code: HTTP status code from Vanta
            response_body: Raw response body for debugging
            retryable: Whether to retry (default True for API errors)
        """
        context = {
            "status_code": status_code,
            "response_body": response_body[:500] if response_body else None,
        }
        super().__init__(message, retryable=retryable, context=context)
        self.status_code = status_code
        self.response_body = response_body


class TerraformParseError(TerraFixError):
    """
    Error parsing Terraform configuration.

    Raised when Terraform HCL parsing fails due to syntax errors or
    unsupported constructs. These are permanent errors that should not
    be retried.

    Attributes:
        file_path: Path to file that failed to parse
        line_number: Line number where error occurred (if available)
    """

    def __init__(
        self,
        message: str,
        file_path: str | None = None,
        line_number: int | None = None,
    ) -> None:
        """
        Initialize Terraform parse error.

        Args:
            message: Human-readable error description
            file_path: Path to file that failed parsing
            line_number: Line number of parse error
        """
        context = {
            "file_path": file_path,
            "line_number": line_number,
        }
        super().__init__(message, retryable=False, context=context)
        self.file_path = file_path
        self.line_number = line_number


class BedrockError(TerraFixError):
    """
    Error calling AWS Bedrock API.

    Raised when Bedrock API calls fail. Common failures include:
    - Throttling (retryable)
    - Invalid credentials (permanent)
    - Model not available (permanent)
    - Timeout (retryable)
    - Invalid request (permanent)

    Attributes:
        error_code: AWS error code
        request_id: AWS request ID for debugging
    """

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        request_id: str | None = None,
        retryable: bool = True,
    ) -> None:
        """
        Initialize Bedrock error.

        Args:
            message: Human-readable error description
            error_code: AWS error code (e.g., ThrottlingException)
            request_id: AWS request ID for support
            retryable: Whether to retry this error
        """
        context = {
            "error_code": error_code,
            "request_id": request_id,
        }
        super().__init__(message, retryable=retryable, context=context)
        self.error_code = error_code
        self.request_id = request_id


class GitHubError(TerraFixError):
    """
    Error communicating with GitHub API.

    Raised when GitHub API operations fail. Common failures include:
    - Rate limiting (retryable with backoff)
    - Network timeouts (retryable)
    - Repository not found (permanent)
    - Insufficient permissions (permanent)
    - Branch already exists (permanent)

    Attributes:
        status_code: HTTP status code
        rate_limit_remaining: Remaining API calls before rate limit
        rate_limit_reset: Unix timestamp when rate limit resets
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        rate_limit_remaining: int | None = None,
        rate_limit_reset: int | None = None,
        retryable: bool = True,
    ) -> None:
        """
        Initialize GitHub error.

        Args:
            message: Human-readable error description
            status_code: HTTP status code from GitHub
            rate_limit_remaining: Remaining API calls
            rate_limit_reset: Unix timestamp of rate limit reset
            retryable: Whether to retry (default True)
        """
        context = {
            "status_code": status_code,
            "rate_limit_remaining": rate_limit_remaining,
            "rate_limit_reset": rate_limit_reset,
        }
        super().__init__(message, retryable=retryable, context=context)
        self.status_code = status_code
        self.rate_limit_remaining = rate_limit_remaining
        self.rate_limit_reset = rate_limit_reset


class StateStoreError(TerraFixError):
    """
    Error accessing SQLite state store.

    Raised when SQLite database operations fail. Most state store errors
    are permanent (schema issues, corruption, disk full) and should not
    be retried.

    Attributes:
        operation: Database operation that failed (e.g., "insert", "query")
        sqlite_error: Original SQLite error message
    """

    def __init__(
        self,
        message: str,
        operation: str | None = None,
        sqlite_error: str | None = None,
    ) -> None:
        """
        Initialize state store error.

        Args:
            message: Human-readable error description
            operation: Database operation that failed
            sqlite_error: Original SQLite error for debugging
        """
        context = {
            "operation": operation,
            "sqlite_error": sqlite_error,
        }
        super().__init__(message, retryable=False, context=context)
        self.operation = operation
        self.sqlite_error = sqlite_error


class ResourceNotFoundError(TerraFixError):
    """
    Error when a Terraform resource cannot be located in the codebase.

    Raised when TerraformAnalyzer cannot find a resource matching the
    provided ARN. This is a permanent error indicating that the resource
    is not managed by Terraform or is in a different repository.

    Attributes:
        resource_arn: AWS resource ARN that was not found
        resource_type: AWS resource type
        searched_files: Number of Terraform files searched
    """

    def __init__(
        self,
        message: str,
        resource_arn: str | None = None,
        resource_type: str | None = None,
        searched_files: int | None = None,
    ) -> None:
        """
        Initialize resource not found error.

        Args:
            message: Human-readable error description
            resource_arn: AWS ARN that was not found
            resource_type: AWS resource type
            searched_files: Number of .tf files searched
        """
        context = {
            "resource_arn": resource_arn,
            "resource_type": resource_type,
            "searched_files": searched_files,
        }
        super().__init__(message, retryable=False, context=context)
        self.resource_arn = resource_arn
        self.resource_type = resource_type
        self.searched_files = searched_files


class ConfigurationError(TerraFixError):
    """
    Error in TerraFix configuration.

    Raised during startup when required configuration is missing or invalid.
    These are permanent errors that require user intervention.

    Attributes:
        config_key: Configuration key that is invalid
        reason: Specific validation failure reason
    """

    def __init__(
        self,
        message: str,
        config_key: str | None = None,
        reason: str | None = None,
    ) -> None:
        """
        Initialize configuration error.

        Args:
            message: Human-readable error description
            config_key: Configuration key that failed validation
            reason: Why the configuration is invalid
        """
        context = {
            "config_key": config_key,
            "reason": reason,
        }
        super().__init__(message, retryable=False, context=context)
        self.config_key = config_key
        self.reason = reason


class TerraformValidationError(TerraFixError):
    """
    Error validating Terraform configuration.

    Raised when terraform fmt or terraform validate fails on a
    generated fix. These are permanent errors indicating the
    AI-generated fix is invalid.

    Attributes:
        validation_errors: List of specific validation error messages
        warnings: List of non-fatal warnings from validation
    """

    def __init__(
        self,
        message: str,
        validation_errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        """
        Initialize Terraform validation error.

        Args:
            message: Human-readable error description
            validation_errors: List of specific validation failures
            warnings: List of non-fatal warnings
        """
        context = {
            "validation_errors": validation_errors or [],
            "warnings": warnings or [],
        }
        super().__init__(message, retryable=False, context=context)
        self.validation_errors = validation_errors or []
        self.warnings = warnings or []

