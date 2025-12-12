"""
Unit tests for configuration module.

Tests cover Settings validation, environment variable parsing,
GitHub repository mapping, and error handling.
"""

import json
from unittest.mock import patch

import pytest
from _pytest.monkeypatch import MonkeyPatch

from terrafix.config import Settings, get_settings
from terrafix.errors import ConfigurationError


class TestSettingsValidation:
    """Tests for Settings validation."""

    def test_settings_from_env_vars(
        self,
        mock_env_vars: dict[str, str],
    ) -> None:
        """Test that Settings loads from environment variables."""
        # Fixture used for side effects
        _ = mock_env_vars
        # Clear the cache first
        get_settings.cache_clear()

        settings = Settings()  # pyright: ignore[reportCallIssue]

        assert settings.vanta_api_token == "test_vanta_token_12345"
        assert settings.github_token == "ghp_test_github_token_67890"
        assert settings.aws_region == "us-west-2"

    def test_missing_vanta_token_raises(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test that missing VANTA_API_TOKEN raises error."""
        monkeypatch.setenv("GITHUB_TOKEN", "test_token")
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        # Set VANTA_API_TOKEN to empty string to trigger validation error
        # (deleting it might still allow .env file to provide a value)
        monkeypatch.setenv("VANTA_API_TOKEN", "")

        get_settings.cache_clear()

        with pytest.raises(ConfigurationError) as exc_info:
            _ = Settings()  # pyright: ignore[reportCallIssue]

        assert "VANTA_API_TOKEN" in str(exc_info.value)

    def test_invalid_log_level_raises(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test that invalid LOG_LEVEL raises error."""
        # Fixture used for side effects
        _ = mock_env_vars
        monkeypatch.setenv("LOG_LEVEL", "INVALID")

        get_settings.cache_clear()

        with pytest.raises(ConfigurationError) as exc_info:
            _ = Settings()  # pyright: ignore[reportCallIssue]

        assert "LOG_LEVEL" in str(exc_info.value)

    def test_invalid_aws_region_raises(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test that invalid AWS_REGION raises error."""
        # Fixture used for side effects
        _ = mock_env_vars
        monkeypatch.setenv("AWS_REGION", "invalid")

        get_settings.cache_clear()

        with pytest.raises(ConfigurationError) as exc_info:
            _ = Settings()  # pyright: ignore[reportCallIssue]

        assert "AWS_REGION" in str(exc_info.value)


class TestGitHubRepoMapping:
    """Tests for GitHub repository mapping."""

    def test_parse_json_string_mapping(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test parsing JSON string for repo mapping."""
        # Fixture used for side effects
        _ = mock_env_vars
        mapping = json.dumps({
            "arn:aws:s3:::prod-": "myorg/prod-terraform",
            "arn:aws:s3:::dev-": "myorg/dev-terraform",
            "default": "myorg/terraform-main",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # pyright: ignore[reportCallIssue]

        assert settings.github_repo_mapping["default"] == "myorg/terraform-main"
        assert len(settings.github_repo_mapping) == 3

    def test_get_repo_for_resource_exact_match(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test exact ARN matching for repo lookup."""
        # Fixture used for side effects
        _ = mock_env_vars
        mapping = json.dumps({
            "arn:aws:s3:::specific-bucket": "myorg/specific-repo",
            "default": "myorg/default-repo",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # pyright: ignore[reportCallIssue]

        repo = settings.get_repo_for_resource("arn:aws:s3:::specific-bucket")
        assert repo == "myorg/specific-repo"

    def test_get_repo_for_resource_prefix_match(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test prefix matching for repo lookup."""
        # Fixture used for side effects
        _ = mock_env_vars
        mapping = json.dumps({
            "arn:aws:s3:::prod-": "myorg/prod-repo",
            "default": "myorg/default-repo",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # pyright: ignore[reportCallIssue]

        repo = settings.get_repo_for_resource("arn:aws:s3:::prod-bucket-123")
        assert repo == "myorg/prod-repo"

    def test_get_repo_for_resource_default_fallback(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test fallback to default repo."""
        # Fixture used for side effects
        _ = mock_env_vars
        mapping = json.dumps({
            "arn:aws:s3:::specific-": "myorg/specific-repo",
            "default": "myorg/default-repo",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # pyright: ignore[reportCallIssue]

        repo = settings.get_repo_for_resource("arn:aws:s3:::other-bucket")
        assert repo == "myorg/default-repo"

    def test_get_repo_for_resource_no_match(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test None returned when no mapping found."""
        # Set up all required env vars explicitly without using mock_env_vars fixture
        # to avoid any contamination from fixtures or .env files
        monkeypatch.setenv("VANTA_API_TOKEN", "test_vanta_token")
        monkeypatch.setenv("GITHUB_TOKEN", "test_github_token")
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        # Use a mapping without a "default" key
        mapping = json.dumps({
            "arn:aws:s3:::specific-": "myorg/specific-repo",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        # Pass _env_file=None to prevent Pydantic from reading .env file
        # which might contain a default GITHUB_REPO_MAPPING
        settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

        repo = settings.get_repo_for_resource("arn:aws:s3:::other-bucket")
        assert repo is None


class TestGetSettings:
    """Tests for get_settings cached function."""

    def test_get_settings_caches_result(
        self,
        mock_env_vars: dict[str, str],
    ) -> None:
        """Test that get_settings caches the Settings instance."""
        # Fixture used for side effects
        _ = mock_env_vars
        get_settings.cache_clear()

        with patch.object(Settings, "validate_boto3_credentials"):
            settings1 = get_settings()
            settings2 = get_settings()

        assert settings1 is settings2  # Same instance

    def test_get_settings_validates_aws_credentials(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test that get_settings validates AWS credentials."""
        # Fixture used for side effects
        _ = mock_env_vars
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)

        get_settings.cache_clear()

        with pytest.raises(ConfigurationError) as exc_info:
            _ = get_settings()

        assert "AWS_ACCESS_KEY_ID" in str(exc_info.value)


class TestSettingsDefaults:
    """Tests for Settings default values."""

    def test_default_poll_interval(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test default poll interval."""
        # Fixture used for side effects
        _ = mock_env_vars
        monkeypatch.delenv("POLL_INTERVAL_SECONDS", raising=False)

        get_settings.cache_clear()

        settings = Settings()  # pyright: ignore[reportCallIssue]

        assert settings.poll_interval_seconds == 300

    def test_default_max_workers(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test default max workers."""
        # Fixture used for side effects
        _ = mock_env_vars
        monkeypatch.delenv("MAX_CONCURRENT_WORKERS", raising=False)

        get_settings.cache_clear()

        settings = Settings()  # pyright: ignore[reportCallIssue]

        assert settings.max_concurrent_workers == 3

    def test_default_log_level(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test default log level."""
        # Fixture used for side effects
        _ = mock_env_vars
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        get_settings.cache_clear()

        settings = Settings()  # pyright: ignore[reportCallIssue]

        assert settings.log_level == "INFO"

