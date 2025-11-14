"""
Configuration management for TerraFix.

This module provides centralized configuration management using Pydantic
settings with validation. All configuration is loaded from environment
variables with explicit validation and clear error messages for missing
or invalid values.

Environment Variables:
    VANTA_API_TOKEN: OAuth token for Vanta API (required)
    GITHUB_TOKEN: GitHub personal access token (required)
    AWS_REGION: AWS region for Bedrock (required)
    AWS_ACCESS_KEY_ID: AWS credentials (required via boto3)
    AWS_SECRET_ACCESS_KEY: AWS credentials (required via boto3)
    BEDROCK_MODEL_ID: Claude model ID (default: anthropic.claude-sonnet-4-5-v2:0)
    POLL_INTERVAL_SECONDS: Polling interval (default: 300)
    SQLITE_PATH: SQLite database path (default: ./terrafix.db)
    GITHUB_REPO_MAPPING: JSON mapping of patterns to repos (optional)
    TERRAFORM_PATH: Path within repos to .tf files (default: .)
    MAX_CONCURRENT_WORKERS: Max parallel processing (default: 3)
    LOG_LEVEL: Logging level (default: INFO)
    VANTA_BASE_URL: Vanta API base URL (default: https://api.vanta.com)
    STATE_RETENTION_DAYS: Days to keep state records (default: 7)

Usage:
    from terrafix.config import get_settings

    settings = get_settings()
    print(settings.vanta_api_token)
"""

import json
import os
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from terrafix.errors import ConfigurationError


class Settings(BaseSettings):
    """
    TerraFix configuration settings.

    All settings are loaded from environment variables with validation.
    Required settings will raise ConfigurationError if missing.
    Optional settings have sensible defaults.

    Attributes:
        vanta_api_token: Vanta OAuth token (required)
        vanta_base_url: Vanta API base URL
        github_token: GitHub personal access token (required)
        github_repo_mapping: Mapping of resource patterns to GitHub repos
        terraform_path: Path within repos to Terraform files
        aws_region: AWS region for Bedrock (required)
        bedrock_model_id: Claude model ID
        poll_interval_seconds: Polling interval in seconds
        sqlite_path: Path to SQLite database file
        max_concurrent_workers: Maximum parallel failure processing
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        state_retention_days: Days to retain processed failure records
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Vanta Configuration
    vanta_api_token: str = Field(
        ...,
        description="Vanta OAuth token with test:read scope",
    )
    vanta_base_url: str = Field(
        default="https://api.vanta.com",
        description="Vanta API base URL",
    )

    # GitHub Configuration
    github_token: str = Field(
        ...,
        description="GitHub personal access token with repo scope",
    )
    github_repo_mapping: dict[str, str] = Field(
        default_factory=lambda: {"default": ""},
        description="Mapping of resource patterns to GitHub repositories",
    )
    terraform_path: str = Field(
        default=".",
        description="Path within repositories to Terraform files",
    )

    # AWS Configuration
    aws_region: str = Field(
        ...,
        description="AWS region for Bedrock API",
    )
    bedrock_model_id: str = Field(
        default="anthropic.claude-sonnet-4-5-v2:0",
        description="AWS Bedrock Claude model ID",
    )

    # Service Configuration
    poll_interval_seconds: int = Field(
        default=300,
        ge=1,
        description="Vanta polling interval in seconds",
    )
    sqlite_path: str = Field(
        default="./terrafix.db",
        description="Path to SQLite database file",
    )
    max_concurrent_workers: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum concurrent failure processing",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    state_retention_days: int = Field(
        default=7,
        ge=1,
        description="Days to retain processed failure records",
    )

    @field_validator("vanta_api_token")
    @classmethod
    def validate_vanta_token(cls, v: str) -> str:
        """
        Validate Vanta API token is not empty.

        Args:
            v: Token value from environment

        Returns:
            Validated token

        Raises:
            ConfigurationError: If token is empty or invalid format
        """
        if not v or not v.strip():
            raise ConfigurationError(
                "VANTA_API_TOKEN is required but not set",
                config_key="VANTA_API_TOKEN",
                reason="Token is empty or missing",
            )
        return v.strip()

    @field_validator("github_token")
    @classmethod
    def validate_github_token(cls, v: str) -> str:
        """
        Validate GitHub token is not empty.

        Args:
            v: Token value from environment

        Returns:
            Validated token

        Raises:
            ConfigurationError: If token is empty or invalid format
        """
        if not v or not v.strip():
            raise ConfigurationError(
                "GITHUB_TOKEN is required but not set",
                config_key="GITHUB_TOKEN",
                reason="Token is empty or missing",
            )
        return v.strip()

    @field_validator("aws_region")
    @classmethod
    def validate_aws_region(cls, v: str) -> str:
        """
        Validate AWS region format.

        Args:
            v: Region value from environment

        Returns:
            Validated region

        Raises:
            ConfigurationError: If region is invalid
        """
        if not v or not v.strip():
            raise ConfigurationError(
                "AWS_REGION is required but not set",
                config_key="AWS_REGION",
                reason="Region is empty or missing",
            )
        # Basic validation for AWS region format
        if not v.count("-") >= 2:
            raise ConfigurationError(
                f"AWS_REGION '{v}' does not appear to be a valid AWS region",
                config_key="AWS_REGION",
                reason="Region format is invalid (expected format: us-west-2)",
            )
        return v.strip()

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """
        Validate log level is recognized.

        Args:
            v: Log level from environment

        Returns:
            Validated log level

        Raises:
            ConfigurationError: If log level is invalid
        """
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ConfigurationError(
                f"LOG_LEVEL '{v}' is not valid. Must be one of: {', '.join(valid_levels)}",
                config_key="LOG_LEVEL",
                reason=f"Invalid log level: {v}",
            )
        return v_upper

    @field_validator("github_repo_mapping", mode="before")
    @classmethod
    def parse_github_repo_mapping(cls, v: Any) -> dict[str, str]:
        """
        Parse GitHub repo mapping from JSON string or dict.

        Args:
            v: Raw value from environment (JSON string or dict)

        Returns:
            Parsed mapping dictionary

        Raises:
            ConfigurationError: If JSON parsing fails
        """
        if isinstance(v, dict):
            return v
        if isinstance(v, str) and v.strip():
            try:
                parsed = json.loads(v)
                if not isinstance(parsed, dict):
                    raise ConfigurationError(
                        "GITHUB_REPO_MAPPING must be a JSON object",
                        config_key="GITHUB_REPO_MAPPING",
                        reason="Parsed JSON is not a dictionary",
                    )
                return parsed
            except json.JSONDecodeError as e:
                raise ConfigurationError(
                    f"GITHUB_REPO_MAPPING is not valid JSON: {e}",
                    config_key="GITHUB_REPO_MAPPING",
                    reason=str(e),
                )
        return {"default": ""}

    def get_repo_for_resource(self, resource_arn: str) -> str | None:
        """
        Get GitHub repository for a given resource ARN.

        Args:
            resource_arn: AWS resource ARN

        Returns:
            GitHub repository (owner/repo) or None if no mapping exists

        Example:
            >>> settings.get_repo_for_resource("arn:aws:s3:::my-bucket")
            "myorg/terraform-aws"
        """
        # Check for exact matches first
        if resource_arn in self.github_repo_mapping:
            return self.github_repo_mapping[resource_arn]

        # Check for pattern matches (simple prefix matching)
        for pattern, repo in self.github_repo_mapping.items():
            if pattern != "default" and resource_arn.startswith(pattern):
                return repo

        # Return default if configured
        default_repo = self.github_repo_mapping.get("default")
        return default_repo if default_repo else None

    def validate_boto3_credentials(self) -> None:
        """
        Validate that boto3 can load AWS credentials.

        This checks that AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
        are available (either via environment or AWS config file).

        Raises:
            ConfigurationError: If AWS credentials are not available
        """
        if not os.getenv("AWS_ACCESS_KEY_ID"):
            raise ConfigurationError(
                "AWS_ACCESS_KEY_ID environment variable is not set",
                config_key="AWS_ACCESS_KEY_ID",
                reason="AWS credentials are required for Bedrock access",
            )
        if not os.getenv("AWS_SECRET_ACCESS_KEY"):
            raise ConfigurationError(
                "AWS_SECRET_ACCESS_KEY environment variable is not set",
                config_key="AWS_SECRET_ACCESS_KEY",
                reason="AWS credentials are required for Bedrock access",
            )


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once per process.
    This is the recommended way to access configuration throughout the
    application.

    Returns:
        Validated Settings instance

    Raises:
        ConfigurationError: If configuration is invalid

    Example:
        >>> from terrafix.config import get_settings
        >>> settings = get_settings()
        >>> print(settings.poll_interval_seconds)
        300
    """
    try:
        settings = Settings()
        settings.validate_boto3_credentials()
        return settings
    except Exception as e:
        if isinstance(e, ConfigurationError):
            raise
        raise ConfigurationError(
            f"Failed to load configuration: {e}",
            reason=str(e),
        ) from e

