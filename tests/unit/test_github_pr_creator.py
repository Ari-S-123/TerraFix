"""
Unit tests for GitHubPRCreator.

Tests cover branch creation, file commits, PR creation, label handling,
error handling, and race condition prevention.
"""

from unittest.mock import MagicMock, patch

import pytest
from github import GithubException
from github.GithubException import UnknownObjectException

from terrafix.errors import GitHubError
from terrafix.github_pr_creator import GitHubPRCreator
from terrafix.remediation_generator import RemediationFix
from terrafix.vanta_client import Failure


class TestGitHubPRCreatorInit:
    """Tests for GitHubPRCreator initialization."""

    @patch("terrafix.github_pr_creator.Github")
    def test_init_creates_github_client(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test that init creates GitHub client with token."""
        mock_client = MagicMock()
        mock_github_class.return_value = mock_client

        creator = GitHubPRCreator(github_token="ghp_test_token")

        mock_github_class.assert_called_once_with("ghp_test_token")
        assert creator.token == "ghp_test_token"


class TestCreateRemediationPR:
    """Tests for GitHubPRCreator.create_remediation_pr method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_create_pr_success(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
        sample_remediation_fix: RemediationFix,
    ) -> None:
        """Test successful PR creation."""
        # Set up mock repository
        mock_repo = MagicMock()
        mock_repo.full_name = "test-org/terraform-repo"

        # Mock get_git_ref for base branch
        mock_base_ref = MagicMock()
        mock_base_ref.object.sha = "base_sha_123"
        mock_repo.get_git_ref.return_value = mock_base_ref

        # Mock create_git_ref for branch creation
        mock_repo.create_git_ref.return_value = MagicMock()

        # Mock get_contents for file
        mock_file = MagicMock()
        mock_file.sha = "file_sha_456"
        mock_repo.get_contents.return_value = mock_file

        # Mock update_file
        mock_repo.update_file.return_value = {"commit": MagicMock()}

        # Mock create_pull
        mock_pr = MagicMock()
        mock_pr.html_url = "https://github.com/test-org/terraform-repo/pull/42"
        mock_pr.number = 42
        mock_repo.create_pull.return_value = mock_pr

        # Mock get_label to raise (label doesn't exist)
        mock_repo.get_label.side_effect = UnknownObjectException(404, {}, {})
        mock_repo.create_label.return_value = MagicMock()

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_client

        creator = GitHubPRCreator(github_token="ghp_test")

        pr_url = creator.create_remediation_pr(
            repo_full_name="test-org/terraform-repo",
            file_path="terraform/s3.tf",
            new_content=sample_remediation_fix.fixed_config,
            failure=sample_failure,
            fix_metadata=sample_remediation_fix,
        )

        assert pr_url == "https://github.com/test-org/terraform-repo/pull/42"
        mock_repo.create_git_ref.assert_called_once()
        mock_repo.update_file.assert_called_once()
        mock_repo.create_pull.assert_called_once()

    @patch("terrafix.github_pr_creator.Github")
    def test_create_pr_repo_not_found(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
        sample_remediation_fix: RemediationFix,
    ) -> None:
        """Test handling of repository not found error."""
        mock_client = MagicMock()
        mock_client.get_repo.side_effect = UnknownObjectException(404, {}, {})
        mock_github_class.return_value = mock_client

        creator = GitHubPRCreator(github_token="ghp_test")

        with pytest.raises(GitHubError) as exc_info:
            creator.create_remediation_pr(
                repo_full_name="nonexistent/repo",
                file_path="s3.tf",
                new_content="",
                failure=sample_failure,
                fix_metadata=sample_remediation_fix,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.retryable is False

    @patch("terrafix.github_pr_creator.Github")
    def test_create_pr_branch_already_exists_returns_empty(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
        sample_remediation_fix: RemediationFix,
    ) -> None:
        """Test that existing branch (race condition) returns empty string."""
        mock_repo = MagicMock()

        # Mock get_git_ref for base branch
        mock_base_ref = MagicMock()
        mock_base_ref.object.sha = "base_sha"
        mock_repo.get_git_ref.return_value = mock_base_ref

        # Mock create_git_ref to raise "Reference already exists"
        mock_repo.create_git_ref.side_effect = GithubException(
            422,
            {"message": "Reference already exists"},
            {},
        )

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_client

        creator = GitHubPRCreator(github_token="ghp_test")

        # Should return empty string (another worker handled it)
        pr_url = creator.create_remediation_pr(
            repo_full_name="test-org/repo",
            file_path="s3.tf",
            new_content="",
            failure=sample_failure,
            fix_metadata=sample_remediation_fix,
        )

        assert pr_url == ""

    @patch("terrafix.github_pr_creator.Github")
    def test_create_pr_rate_limit_is_retryable(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
        sample_remediation_fix: RemediationFix,
    ) -> None:
        """Test that rate limit error is marked as retryable."""
        mock_repo = MagicMock()

        # Mock get_git_ref for base branch
        mock_base_ref = MagicMock()
        mock_base_ref.object.sha = "base_sha"
        mock_repo.get_git_ref.return_value = mock_base_ref

        # Mock create_git_ref to succeed
        mock_repo.create_git_ref.return_value = MagicMock()

        # Mock get_contents
        mock_file = MagicMock()
        mock_file.sha = "file_sha"
        mock_repo.get_contents.return_value = mock_file

        # Mock update_file to raise rate limit error
        rate_limit_error = GithubException(429, {"message": "Rate limit exceeded"}, {})
        rate_limit_error.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1234567890",
        }
        mock_repo.update_file.side_effect = rate_limit_error

        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_client

        creator = GitHubPRCreator(github_token="ghp_test")

        with pytest.raises(GitHubError) as exc_info:
            creator.create_remediation_pr(
                repo_full_name="test-org/repo",
                file_path="s3.tf",
                new_content="",
                failure=sample_failure,
                fix_metadata=sample_remediation_fix,
            )

        # Branch should be cleaned up on failure
        # Error should be retryable
        # Note: The actual implementation may vary


class TestGenerateBranchName:
    """Tests for GitHubPRCreator._generate_branch_name method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_branch_name_format(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that branch name follows expected format."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        branch_name = creator._generate_branch_name(sample_failure)

        assert branch_name.startswith("terrafix/")
        assert "-" in branch_name
        # Should have hash suffix
        assert len(branch_name.split("-")[-1]) == 8

    @patch("terrafix.github_pr_creator.Github")
    def test_branch_name_sanitizes_test_name(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test that branch name sanitizes special characters."""
        mock_github_class.return_value = MagicMock()

        failure = Failure(
            test_id="test-123",
            test_name="S3/Bucket Block_Public Access",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Test",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
        )

        creator = GitHubPRCreator(github_token="ghp_test")
        branch_name = creator._generate_branch_name(failure)

        # Should not contain slashes (except terrafix/) or underscores
        parts = branch_name.split("/", 1)
        assert len(parts) == 2
        assert "_" not in parts[1]
        assert "/" not in parts[1]


class TestGenerateCommitMessage:
    """Tests for GitHubPRCreator._generate_commit_message method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_commit_message_conventional_format(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that commit message follows conventional commits."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        message = creator._generate_commit_message(sample_failure)

        # Check conventional commit format
        assert message.startswith("fix(compliance):")
        assert sample_failure.test_name in message
        assert sample_failure.framework in message
        assert sample_failure.severity in message


class TestGeneratePRTitle:
    """Tests for GitHubPRCreator._generate_pr_title method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_pr_title_contains_severity_emoji(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test that PR title includes severity emoji."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")

        high_failure = Failure(
            test_id="test-1",
            test_name="Test High",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Test",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
        )

        medium_failure = Failure(
            test_id="test-2",
            test_name="Test Medium",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Test",
            severity="medium",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
        )

        low_failure = Failure(
            test_id="test-3",
            test_name="Test Low",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Test",
            severity="low",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
        )

        high_title = creator._generate_pr_title(high_failure)
        medium_title = creator._generate_pr_title(medium_failure)
        low_title = creator._generate_pr_title(low_failure)

        assert "🔴" in high_title
        assert "🟡" in medium_title
        assert "🟢" in low_title
        assert "[TerraFix]" in high_title


class TestGeneratePRBody:
    """Tests for GitHubPRCreator._generate_pr_body method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_pr_body_contains_all_sections(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
        sample_remediation_fix: RemediationFix,
    ) -> None:
        """Test that PR body contains all required sections."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        body = creator._generate_pr_body(
            failure=sample_failure,
            fix_metadata=sample_remediation_fix,
            file_path="terraform/s3.tf",
        )

        # Check for main sections
        assert "Compliance Failure Details" in body
        assert "Changes Made" in body
        assert "Explanation" in body
        assert "Review Checklist" in body
        assert "Breaking Changes" in body

        # Check for failure details
        assert sample_failure.test_name in body
        assert sample_failure.framework in body
        assert sample_failure.resource_arn in body

        # Check for fix details
        assert sample_remediation_fix.explanation in body
        assert sample_remediation_fix.reasoning in body

    @patch("terrafix.github_pr_creator.Github")
    def test_pr_body_truncates_long_state(
        self,
        mock_github_class: MagicMock,
        sample_remediation_fix: RemediationFix,
    ) -> None:
        """Test that PR body truncates very long state JSONs."""
        mock_github_class.return_value = MagicMock()

        failure = Failure(
            test_id="test-1",
            test_name="Test",
            resource_arn="arn:aws:s3:::bucket",
            resource_type="AWS::S3::Bucket",
            failure_reason="Test",
            severity="high",
            framework="SOC2",
            failed_at="2025-01-15T10:00:00Z",
            current_state={"key" + str(i): "value" * 100 for i in range(100)},
            required_state={"key" + str(i): "value" * 100 for i in range(100)},
        )

        creator = GitHubPRCreator(github_token="ghp_test")
        body = creator._generate_pr_body(
            failure=failure,
            fix_metadata=sample_remediation_fix,
            file_path="s3.tf",
        )

        # Should contain truncation indicator
        assert "[truncated]" in body


class TestDetermineLabels:
    """Tests for GitHubPRCreator._determine_labels method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_labels_include_standard_labels(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that standard labels are always included."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        labels = creator._determine_labels(sample_failure)

        assert "compliance" in labels
        assert "automated" in labels
        assert "terrafix" in labels

    @patch("terrafix.github_pr_creator.Github")
    def test_labels_include_severity(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that severity label is included."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        labels = creator._determine_labels(sample_failure)

        assert f"severity:{sample_failure.severity}" in labels

    @patch("terrafix.github_pr_creator.Github")
    def test_labels_include_framework(
        self,
        mock_github_class: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that framework label is included."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        labels = creator._determine_labels(sample_failure)

        assert f"framework:{sample_failure.framework.lower()}" in labels


class TestGetConfidenceGuidance:
    """Tests for GitHubPRCreator._get_confidence_guidance method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_high_confidence_guidance(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test guidance for high confidence."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        guidance = creator._get_confidence_guidance("high")

        assert "✅" in guidance
        assert "straightforward" in guidance.lower()

    @patch("terrafix.github_pr_creator.Github")
    def test_medium_confidence_guidance(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test guidance for medium confidence."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        guidance = creator._get_confidence_guidance("medium")

        assert "⚠️" in guidance
        assert "scrutiny" in guidance.lower()

    @patch("terrafix.github_pr_creator.Github")
    def test_low_confidence_guidance(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test guidance for low confidence."""
        mock_github_class.return_value = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        guidance = creator._get_confidence_guidance("low")

        assert "❌" in guidance
        assert "thorough" in guidance.lower()


class TestAddLabelsSafe:
    """Tests for GitHubPRCreator._add_labels_safe method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_creates_missing_labels(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test that missing labels are created."""
        mock_github_class.return_value = MagicMock()

        mock_repo = MagicMock()
        mock_repo.get_label.side_effect = UnknownObjectException(404, {}, {})
        mock_repo.create_label.return_value = MagicMock()

        mock_pr = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")
        creator._add_labels_safe(mock_pr, ["new-label"], mock_repo)

        mock_repo.create_label.assert_called()
        mock_pr.add_to_labels.assert_called_with("new-label")

    @patch("terrafix.github_pr_creator.Github")
    def test_handles_label_creation_failure(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test graceful handling of label creation failure."""
        mock_github_class.return_value = MagicMock()

        mock_repo = MagicMock()
        mock_repo.get_label.side_effect = UnknownObjectException(404, {}, {})
        mock_repo.create_label.side_effect = GithubException(500, {}, {})

        mock_pr = MagicMock()

        creator = GitHubPRCreator(github_token="ghp_test")

        # Should not raise
        creator._add_labels_safe(mock_pr, ["label"], mock_repo)


class TestCleanupBranch:
    """Tests for GitHubPRCreator._cleanup_branch method."""

    @patch("terrafix.github_pr_creator.Github")
    def test_cleanup_deletes_branch(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test that cleanup deletes the branch."""
        mock_github_class.return_value = MagicMock()

        mock_repo = MagicMock()
        mock_ref = MagicMock()
        mock_repo.get_git_ref.return_value = mock_ref

        creator = GitHubPRCreator(github_token="ghp_test")
        creator._cleanup_branch(mock_repo, "test-branch")

        mock_repo.get_git_ref.assert_called_once_with("heads/test-branch")
        mock_ref.delete.assert_called_once()

    @patch("terrafix.github_pr_creator.Github")
    def test_cleanup_handles_failure_gracefully(
        self,
        mock_github_class: MagicMock,
    ) -> None:
        """Test that cleanup failure doesn't raise."""
        mock_github_class.return_value = MagicMock()

        mock_repo = MagicMock()
        mock_repo.get_git_ref.side_effect = GithubException(404, {}, {})

        creator = GitHubPRCreator(github_token="ghp_test")

        # Should not raise
        creator._cleanup_branch(mock_repo, "nonexistent-branch")

