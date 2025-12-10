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
        # Clear the cache first
        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

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
        # Don't set VANTA_API_TOKEN
        monkeypatch.delenv("VANTA_API_TOKEN", raising=False)

        get_settings.cache_clear()

        with pytest.raises(Exception):  # Pydantic validation error
            Settings()  # type: ignore[call-arg]

    def test_invalid_log_level_raises(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test that invalid LOG_LEVEL raises error."""
        monkeypatch.setenv("LOG_LEVEL", "INVALID")

        get_settings.cache_clear()

        with pytest.raises(ConfigurationError) as exc_info:
            Settings()  # type: ignore[call-arg]

        assert "LOG_LEVEL" in str(exc_info.value)

    def test_invalid_aws_region_raises(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test that invalid AWS_REGION raises error."""
        monkeypatch.setenv("AWS_REGION", "invalid")

        get_settings.cache_clear()

        with pytest.raises(ConfigurationError) as exc_info:
            Settings()  # type: ignore[call-arg]

        assert "AWS_REGION" in str(exc_info.value)


class TestGitHubRepoMapping:
    """Tests for GitHub repository mapping."""

    def test_parse_json_string_mapping(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test parsing JSON string for repo mapping."""
        mapping = json.dumps({
            "arn:aws:s3:::prod-": "myorg/prod-terraform",
            "arn:aws:s3:::dev-": "myorg/dev-terraform",
            "default": "myorg/terraform-main",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

        assert settings.github_repo_mapping["default"] == "myorg/terraform-main"
        assert len(settings.github_repo_mapping) == 3

    def test_get_repo_for_resource_exact_match(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test exact ARN matching for repo lookup."""
        mapping = json.dumps({
            "arn:aws:s3:::specific-bucket": "myorg/specific-repo",
            "default": "myorg/default-repo",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

        repo = settings.get_repo_for_resource("arn:aws:s3:::specific-bucket")
        assert repo == "myorg/specific-repo"

    def test_get_repo_for_resource_prefix_match(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test prefix matching for repo lookup."""
        mapping = json.dumps({
            "arn:aws:s3:::prod-": "myorg/prod-repo",
            "default": "myorg/default-repo",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

        repo = settings.get_repo_for_resource("arn:aws:s3:::prod-bucket-123")
        assert repo == "myorg/prod-repo"

    def test_get_repo_for_resource_default_fallback(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test fallback to default repo."""
        mapping = json.dumps({
            "arn:aws:s3:::specific-": "myorg/specific-repo",
            "default": "myorg/default-repo",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

        repo = settings.get_repo_for_resource("arn:aws:s3:::other-bucket")
        assert repo == "myorg/default-repo"

    def test_get_repo_for_resource_no_match(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test None returned when no mapping found."""
        mapping = json.dumps({
            "arn:aws:s3:::specific-": "myorg/specific-repo",
        })
        monkeypatch.setenv("GITHUB_REPO_MAPPING", mapping)

        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

        repo = settings.get_repo_for_resource("arn:aws:s3:::other-bucket")
        assert repo is None


class TestGetSettings:
    """Tests for get_settings cached function."""

    def test_get_settings_caches_result(
        self,
        mock_env_vars: dict[str, str],
    ) -> None:
        """Test that get_settings caches the Settings instance."""
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
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)

        get_settings.cache_clear()

        with pytest.raises(ConfigurationError) as exc_info:
            get_settings()

        assert "AWS_ACCESS_KEY_ID" in str(exc_info.value)


class TestSettingsDefaults:
    """Tests for Settings default values."""

    def test_default_poll_interval(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test default poll interval."""
        monkeypatch.delenv("POLL_INTERVAL_SECONDS", raising=False)

        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

        assert settings.poll_interval_seconds == 300

    def test_default_max_workers(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test default max workers."""
        monkeypatch.delenv("MAX_CONCURRENT_WORKERS", raising=False)

        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

        assert settings.max_concurrent_workers == 3

    def test_default_log_level(
        self,
        mock_env_vars: dict[str, str],
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test default log level."""
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        get_settings.cache_clear()

        settings = Settings()  # type: ignore[call-arg]

        assert settings.log_level == "INFO"

