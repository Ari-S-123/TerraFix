"""
Unit tests for the orchestrator module.

Tests cover the end-to-end processing pipeline, deduplication,
retry logic, error handling, and validation.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from terrafix.config import Settings
from terrafix.errors import (
    BedrockError,
    GitHubError,
    ResourceNotFoundError,
    TerraFixError,
)
from terrafix.orchestrator import (
    ProcessingResult,
    _process_failure_once,  # pyright: ignore[reportPrivateUsage]
    _process_failure_with_retry,  # pyright: ignore[reportPrivateUsage]
    process_failure,
)
from terrafix.redis_state_store import RedisStateStore
from terrafix.remediation_generator import RemediationFix, TerraformRemediationGenerator
from terrafix.vanta_client import Failure, VantaClient


class TestProcessingResult:
    """Tests for the ProcessingResult class."""

    def test_success_result(self) -> None:
        """Test creating a successful processing result."""
        result = ProcessingResult(
            success=True,
            failure_hash="abc123",
            pr_url="https://github.com/org/repo/pull/1",
        )

        assert result.success is True
        assert result.failure_hash == "abc123"
        assert result.pr_url == "https://github.com/org/repo/pull/1"
        assert result.error is None
        assert result.skipped is False

    def test_failure_result(self) -> None:
        """Test creating a failed processing result."""
        result = ProcessingResult(
            success=False,
            failure_hash="abc123",
            error="Something went wrong",
        )

        assert result.success is False
        assert result.error == "Something went wrong"
        assert result.pr_url is None

    def test_skipped_result(self) -> None:
        """Test creating a skipped processing result."""
        result = ProcessingResult(
            success=True,
            failure_hash="abc123",
            skipped=True,
        )

        assert result.success is True
        assert result.skipped is True


class TestProcessFailure:
    """Tests for the process_failure function."""

    @patch("terrafix.orchestrator._process_failure_with_retry")
    def test_process_failure_already_processed_skips(
        self,
        mock_retry: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test that already-processed failures are skipped."""
        # Mock state store
        mock_state_store = MagicMock(spec=RedisStateStore)
        mock_state_store.is_already_processed.return_value = True  # pyright: ignore[reportAny]

        # Mock vanta client
        mock_vanta = MagicMock(spec=VantaClient)
        mock_vanta.generate_failure_hash.return_value = "existing_hash"  # pyright: ignore[reportAny]

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        result = process_failure(
            failure=sample_failure,
            config=mock_settings,
            state_store=mock_state_store,
            vanta=mock_vanta,
            generator=mock_generator,
            gh=mock_gh,
        )

        assert result.success is True
        assert result.skipped is True
        mock_retry.assert_not_called()

    @patch("terrafix.orchestrator._process_failure_with_retry")
    def test_process_failure_success(
        self,
        mock_retry: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test successful failure processing."""
        mock_retry.return_value = "https://github.com/org/repo/pull/42"

        # Mock state store
        mock_state_store = MagicMock(spec=RedisStateStore)
        mock_state_store.is_already_processed.return_value = False  # pyright: ignore[reportAny]

        # Mock vanta client
        mock_vanta = MagicMock(spec=VantaClient)
        mock_vanta.generate_failure_hash.return_value = "new_hash"  # pyright: ignore[reportAny]

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        result = process_failure(
            failure=sample_failure,
            config=mock_settings,
            state_store=mock_state_store,
            vanta=mock_vanta,
            generator=mock_generator,
            gh=mock_gh,
        )

        assert result.success is True
        assert result.pr_url == "https://github.com/org/repo/pull/42"
        mock_state_store.mark_in_progress.assert_called_once()  # pyright: ignore[reportAny]
        mock_state_store.mark_processed.assert_called_once()  # pyright: ignore[reportAny]

    @patch("terrafix.orchestrator._process_failure_with_retry")
    def test_process_failure_marks_failed_on_error(
        self,
        mock_retry: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test that failures are marked in state store on error."""
        mock_retry.side_effect = TerraFixError("Test error", retryable=False)

        # Mock state store
        mock_state_store = MagicMock(spec=RedisStateStore)
        mock_state_store.is_already_processed.return_value = False  # pyright: ignore[reportAny]

        # Mock vanta client
        mock_vanta = MagicMock(spec=VantaClient)
        mock_vanta.generate_failure_hash.return_value = "failed_hash"  # pyright: ignore[reportAny]

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        result = process_failure(
            failure=sample_failure,
            config=mock_settings,
            state_store=mock_state_store,
            vanta=mock_vanta,
            generator=mock_generator,
            gh=mock_gh,
        )

        assert result.success is False
        assert result.error is not None and "Test error" in result.error
        mock_state_store.mark_failed.assert_called_once()  # pyright: ignore[reportAny]


class TestProcessFailureWithRetry:
    """Tests for the _process_failure_with_retry function."""

    @patch("terrafix.orchestrator._process_failure_once")
    def test_retry_on_transient_error(
        self,
        mock_process_once: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test that transient errors trigger retries."""
        # First call fails with retryable error, second succeeds
        mock_process_once.side_effect = [
            BedrockError("Throttling", retryable=True),
            "https://github.com/org/repo/pull/1",
        ]

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        with patch("terrafix.orchestrator.time.sleep"):  # Skip actual sleep
            result = _process_failure_with_retry(
                failure=sample_failure,
                config=mock_settings,
                generator=mock_generator,
                gh=mock_gh,
            )

        assert result == "https://github.com/org/repo/pull/1"
        assert mock_process_once.call_count == 2

    @patch("terrafix.orchestrator._process_failure_once")
    def test_no_retry_on_permanent_error(
        self,
        mock_process_once: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test that permanent errors don't trigger retries."""
        mock_process_once.side_effect = ResourceNotFoundError(
            "Resource not found",
            resource_arn="arn:aws:s3:::bucket",
        )

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        with pytest.raises(ResourceNotFoundError):
            _ = _process_failure_with_retry(
                failure=sample_failure,
                config=mock_settings,
                generator=mock_generator,
                gh=mock_gh,
            )

        # Should only be called once
        assert mock_process_once.call_count == 1

    @patch("terrafix.orchestrator._process_failure_once")
    def test_no_retry_on_non_retryable_api_error(
        self,
        mock_process_once: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test that non-retryable API errors don't trigger retries."""
        mock_process_once.side_effect = BedrockError(
            "Invalid model",
            retryable=False,
        )

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        with pytest.raises(BedrockError):
            _ = _process_failure_with_retry(
                failure=sample_failure,
                config=mock_settings,
                generator=mock_generator,
                gh=mock_gh,
            )

        assert mock_process_once.call_count == 1

    @patch("terrafix.orchestrator._process_failure_once")
    def test_max_retries_exceeded(
        self,
        mock_process_once: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test that processing fails after max retries."""
        # All calls fail with retryable error
        mock_process_once.side_effect = GitHubError(
            "Server error",
            retryable=True,
        )

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        with patch("terrafix.orchestrator.time.sleep"):  # Skip actual sleep
            with pytest.raises(GitHubError):
                _ = _process_failure_with_retry(
                    failure=sample_failure,
                    config=mock_settings,
                    generator=mock_generator,
                    gh=mock_gh,
                )

        # Should hit max retries (3)
        assert mock_process_once.call_count == 3


class TestProcessFailureOnce:
    """Tests for the _process_failure_once function."""

    @patch("terrafix.orchestrator.SecureGitClient")
    @patch("terrafix.orchestrator.TerraformAnalyzer")
    @patch("terrafix.orchestrator.TerraformValidator")
    def test_process_failure_once_success(
        self,
        mock_validator_class: MagicMock,
        mock_analyzer_class: MagicMock,
        mock_git_class: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
        sample_remediation_fix: RemediationFix,
    ) -> None:
        """Test successful single attempt processing."""
        # Mock git client
        mock_git = MagicMock()
        mock_git_class.return_value = mock_git

        # Mock validator
        mock_validator = MagicMock()
        mock_validator.validate_configuration.return_value = MagicMock(  # pyright: ignore[reportAny]
            is_valid=True,
            formatted_content=sample_remediation_fix.fixed_config,
            warnings=[],
        )
        mock_validator_class.return_value = mock_validator

        # Mock generator
        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_generator.generate_fix.return_value = sample_remediation_fix  # pyright: ignore[reportAny]

        # Mock GitHub PR creator
        mock_gh = MagicMock()
        mock_gh.create_remediation_pr.return_value = "https://github.com/org/repo/pull/1"  # pyright: ignore[reportAny]

        # Create a temporary directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create terraform path
            terraform_path = Path(temp_dir) / "repo" / "terraform"
            terraform_path.mkdir(parents=True)
            _ = (terraform_path / "s3.tf").write_text('resource "aws_s3_bucket" "test" {}')

            # Mock analyzer - use path relative to our actual temp directory
            # to avoid Unix/Windows path mismatches
            mock_analyzer = MagicMock()
            mock_analyzer.find_resource_by_arn.return_value = (  # pyright: ignore[reportAny]
                str(terraform_path / "s3.tf"),  # Use actual temp path, not hardcoded Unix path
                {"bucket": "test"},
                "test_bucket",
            )
            mock_analyzer.get_module_context.return_value = {}  # pyright: ignore[reportAny]
            mock_analyzer.get_file_content.return_value = 'resource "aws_s3_bucket" {}'  # pyright: ignore[reportAny]
            mock_analyzer.terraform_files = ["s3.tf"]
            mock_analyzer_class.return_value = mock_analyzer

            # Patch tempfile to use our temp dir
            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_tempdir.return_value.__enter__.return_value = temp_dir  # pyright: ignore[reportAny]
                mock_tempdir.return_value.__exit__ = MagicMock(return_value=False)  # pyright: ignore[reportAny]

                # Configure settings to use terraform subdirectory
                mock_settings.terraform_path = "terraform"

                pr_url = _process_failure_once(
                    failure=sample_failure,
                    config=mock_settings,
                    generator=mock_generator,
                    gh=mock_gh,
                )

        assert pr_url == "https://github.com/org/repo/pull/1"
        mock_generator.generate_fix.assert_called_once()  # pyright: ignore[reportAny]
        mock_gh.create_remediation_pr.assert_called_once()  # pyright: ignore[reportAny]

    @patch("terrafix.orchestrator.SecureGitClient")
    def test_process_failure_once_no_repo_mapping(
        self,
        mock_git_class: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test error when no repository mapping exists."""
        # Used for patching
        _ = mock_git_class
        # Override settings to have no repo mapping
        mock_settings.github_repo_mapping = {}

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        with pytest.raises(ResourceNotFoundError) as exc_info:
            _ = _process_failure_once(
                failure=sample_failure,
                config=mock_settings,
                generator=mock_generator,
                gh=mock_gh,
            )

        assert "No repository mapping found" in str(exc_info.value)

    @patch("terrafix.orchestrator.SecureGitClient")
    @patch("terrafix.orchestrator.TerraformAnalyzer")
    def test_process_failure_once_resource_not_found(
        self,
        mock_analyzer_class: MagicMock,
        mock_git_class: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test error when resource not found in Terraform."""
        # Mock git client
        mock_git = MagicMock()
        mock_git_class.return_value = mock_git

        # Mock analyzer to not find resource
        mock_analyzer = MagicMock()
        mock_analyzer.find_resource_by_arn.return_value = None  # pyright: ignore[reportAny]
        mock_analyzer.terraform_files = ["main.tf"]
        mock_analyzer_class.return_value = mock_analyzer

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_gh = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            terraform_path = Path(temp_dir) / "repo" / "terraform"
            terraform_path.mkdir(parents=True)
            _ = (terraform_path / "main.tf").write_text("")

            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_tempdir.return_value.__enter__.return_value = temp_dir  # pyright: ignore[reportAny]
                mock_tempdir.return_value.__exit__ = MagicMock(return_value=False)  # pyright: ignore[reportAny]

                mock_settings.terraform_path = "terraform"

                with pytest.raises(ResourceNotFoundError) as exc_info:
                    _ = _process_failure_once(
                        failure=sample_failure,
                        config=mock_settings,
                        generator=mock_generator,
                        gh=mock_gh,
                    )

        assert "not found in Terraform" in str(exc_info.value)

    @patch("terrafix.orchestrator.SecureGitClient")
    @patch("terrafix.orchestrator.TerraformAnalyzer")
    @patch("terrafix.orchestrator.TerraformValidator")
    def test_process_failure_once_empty_fix_raises(
        self,
        mock_validator_class: MagicMock,
        mock_analyzer_class: MagicMock,
        mock_git_class: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
    ) -> None:
        """Test error when generated fix is empty."""
        # Unused but required for patching
        _ = mock_validator_class
        # Mock git client
        mock_git = MagicMock()
        mock_git_class.return_value = mock_git

        # Mock analyzer
        mock_analyzer = MagicMock()
        mock_analyzer.find_resource_by_arn.return_value = (  # pyright: ignore[reportAny]
            "/tmp/repo/s3.tf",
            {"bucket": "test"},
            "test_bucket",
        )
        mock_analyzer.get_module_context.return_value = {}  # pyright: ignore[reportAny]
        mock_analyzer.get_file_content.return_value = ""  # pyright: ignore[reportAny]
        mock_analyzer_class.return_value = mock_analyzer

        # Mock generator to return empty fix
        empty_fix = RemediationFix(
            fixed_config="",  # Empty!
            explanation="Test",
            confidence="high",
        )
        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_generator.generate_fix.return_value = empty_fix  # pyright: ignore[reportAny]

        mock_gh = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            terraform_path = Path(temp_dir) / "repo" / "terraform"
            terraform_path.mkdir(parents=True)
            _ = (terraform_path / "s3.tf").write_text("")

            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_tempdir.return_value.__enter__.return_value = temp_dir  # pyright: ignore[reportAny]
                mock_tempdir.return_value.__exit__ = MagicMock(return_value=False)  # pyright: ignore[reportAny]

                mock_settings.terraform_path = "terraform"

                with pytest.raises(TerraFixError) as exc_info:
                    _ = _process_failure_once(
                        failure=sample_failure,
                        config=mock_settings,
                        generator=mock_generator,
                        gh=mock_gh,
                    )

        assert "empty" in str(exc_info.value).lower()

    @patch("terrafix.orchestrator.SecureGitClient")
    @patch("terrafix.orchestrator.TerraformAnalyzer")
    @patch("terrafix.orchestrator.TerraformValidator")
    def test_process_failure_once_invalid_fix_raises(
        self,
        mock_validator_class: MagicMock,
        mock_analyzer_class: MagicMock,
        mock_git_class: MagicMock,
        mock_settings: Settings,
        sample_failure: Failure,
        sample_remediation_fix: RemediationFix,
    ) -> None:
        """Test error when generated fix fails validation."""
        # Mock git client
        mock_git = MagicMock()
        mock_git_class.return_value = mock_git

        # Mock analyzer
        mock_analyzer = MagicMock()
        mock_analyzer.find_resource_by_arn.return_value = (  # pyright: ignore[reportAny]
            "/tmp/repo/s3.tf",
            {"bucket": "test"},
            "test_bucket",
        )
        mock_analyzer.get_module_context.return_value = {}  # pyright: ignore[reportAny]
        mock_analyzer.get_file_content.return_value = ""  # pyright: ignore[reportAny]
        mock_analyzer_class.return_value = mock_analyzer

        # Mock validator to fail
        mock_validator = MagicMock()
        mock_validator.validate_configuration.return_value = MagicMock(  # pyright: ignore[reportAny]
            is_valid=False,
            formatted_content=None,
            error_message="Invalid HCL syntax",
            warnings=[],
        )
        mock_validator_class.return_value = mock_validator

        mock_generator = MagicMock(spec=TerraformRemediationGenerator)
        mock_generator.generate_fix.return_value = sample_remediation_fix  # pyright: ignore[reportAny]

        mock_gh = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            terraform_path = Path(temp_dir) / "repo" / "terraform"
            terraform_path.mkdir(parents=True)
            _ = (terraform_path / "s3.tf").write_text("")

            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_tempdir.return_value.__enter__.return_value = temp_dir  # pyright: ignore[reportAny]
                mock_tempdir.return_value.__exit__ = MagicMock(return_value=False)  # pyright: ignore[reportAny]

                mock_settings.terraform_path = "terraform"

                with pytest.raises(TerraFixError) as exc_info:
                    _ = _process_failure_once(
                        failure=sample_failure,
                        config=mock_settings,
                        generator=mock_generator,
                        gh=mock_gh,
                    )

        assert "invalid" in str(exc_info.value).lower()


class TestConfigTests:
    """Tests for configuration validation."""

    def test_config_fixture_provides_valid_settings(
        self,
        mock_settings: Settings,
    ) -> None:
        """Test that mock_settings fixture provides valid Settings."""
        assert mock_settings.vanta_api_token is not None
        assert mock_settings.github_token is not None
        assert mock_settings.aws_region is not None
        assert mock_settings.github_repo_mapping is not None

    def test_config_get_repo_for_resource_default(
        self,
        mock_settings: Settings,
    ) -> None:
        """Test get_repo_for_resource with default mapping."""
        repo = mock_settings.get_repo_for_resource("arn:aws:s3:::any-bucket")

        assert repo == "test-org/terraform-repo"

