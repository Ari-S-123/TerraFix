"""
GitHub integration for creating Pull Requests with Terraform fixes.

This module uses PyGithub to clone repos, create branches, commit changes,
and open PRs with rich context for reviewers. It handles GitHub API
rate limiting and error conditions.

Usage:
    from terrafix.github_pr_creator import GitHubPRCreator

    creator = GitHubPRCreator(github_token="ghp_...")
    
    pr_url = creator.create_remediation_pr(
        repo_full_name="org/terraform-repo",
        file_path="terraform/s3.tf",
        new_content=fixed_config,
        failure=failure,
        fix_metadata=fix
    )
    
    print(f"Created PR: {pr_url}")
"""

import hashlib
import json
from typing import Any

from github import Github, GithubException
from github.GithubException import UnknownObjectException

from terrafix.errors import GitHubError
from terrafix.logging_config import get_logger, log_with_context
from terrafix.remediation_generator import RemediationFix
from terrafix.vanta_client import Failure

logger = get_logger(__name__)


class GitHubPRCreator:
    """
    Handles Git operations and GitHub PR creation.

    Uses PyGithub to interact with the GitHub API, creating branches,
    updating files, and opening pull requests with comprehensive context.

    Attributes:
        gh_client: PyGithub client instance
        token: GitHub personal access token
    """

    def __init__(self, github_token: str) -> None:
        """
        Initialize GitHub client.

        Args:
            github_token: GitHub PAT with repo scope

        Example:
            >>> creator = GitHubPRCreator(github_token="ghp_...")
        """
        self.gh_client = Github(github_token)
        self.token = github_token

        log_with_context(
            logger,
            "info",
            "Initialized GitHub client",
        )

    def create_remediation_pr(
        self,
        repo_full_name: str,
        file_path: str,
        new_content: str,
        failure: Failure,
        fix_metadata: RemediationFix,
        base_branch: str = "main",
    ) -> str:
        """
        Create Pull Request with Terraform fix.

        Creates a new branch, commits the fixed configuration, and opens
        a PR with comprehensive review context.

        Args:
            repo_full_name: GitHub repo (owner/repo)
            file_path: Path to file being modified
            new_content: Fixed Terraform configuration
            failure: Original Vanta failure details
            fix_metadata: Claude's fix metadata (explanation, etc.)
            base_branch: Target branch for PR (default: main)

        Returns:
            Pull Request URL

        Raises:
            GitHubError: If GitHub API operations fail

        Example:
            >>> pr_url = creator.create_remediation_pr(
            ...     "org/repo",
            ...     "s3.tf",
            ...     fixed_config,
            ...     failure,
            ...     fix
            ... )
        """
        log_with_context(
            logger,
            "info",
            "Creating remediation PR",
            repo=repo_full_name,
            file_path=file_path,
            test_id=failure.test_id,
        )

        try:
            repo = self.gh_client.get_repo(repo_full_name)
        except UnknownObjectException as e:
            raise GitHubError(
                f"Repository {repo_full_name} not found",
                status_code=404,
                retryable=False,
            ) from e
        except GithubException as e:
            raise self._handle_github_exception(e, "get_repo") from e

        # Generate branch name
        branch_name = self._generate_branch_name(failure)

        # Check if branch already exists (avoid duplicates)
        try:
            repo.get_branch(branch_name)
            log_with_context(
                logger,
                "warning",
                "Branch already exists, skipping PR creation",
                branch_name=branch_name,
            )
            # Return None to indicate duplicate
            return ""
        except UnknownObjectException:
            pass  # Branch doesn't exist, continue

        try:
            # Get base branch reference
            base_ref = repo.get_git_ref(f"heads/{base_branch}")
            base_sha = base_ref.object.sha

            # Create new branch
            repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base_sha,
            )

            log_with_context(
                logger,
                "info",
                "Created branch",
                branch_name=branch_name,
                base_sha=base_sha,
            )

            # Update file on new branch
            # Get current file to obtain its SHA
            file_content = repo.get_contents(file_path, ref=base_branch)

            # Commit updated file
            commit_message = self._generate_commit_message(failure)

            repo.update_file(
                path=file_path,
                message=commit_message,
                content=new_content,
                sha=file_content.sha,
                branch=branch_name,
            )

            log_with_context(
                logger,
                "info",
                "Committed changes",
                file_path=file_path,
                branch_name=branch_name,
            )

            # Create Pull Request
            pr_title = self._generate_pr_title(failure)
            pr_body = self._generate_pr_body(failure, fix_metadata, file_path)

            pr = repo.create_pull(
                title=pr_title,
                body=pr_body,
                head=branch_name,
                base=base_branch,
            )

            # Add labels (create them if they don't exist)
            labels = self._determine_labels(failure)
            self._add_labels_safe(pr, labels, repo)

            log_with_context(
                logger,
                "info",
                "Created Pull Request",
                pr_url=pr.html_url,
                pr_number=pr.number,
            )

            return pr.html_url

        except GithubException as e:
            raise self._handle_github_exception(e, "create_pr") from e

    def _handle_github_exception(
        self,
        exception: GithubException,
        operation: str,
    ) -> GitHubError:
        """
        Convert GitHub exception to GitHubError.

        Args:
            exception: Original GitHub exception
            operation: Operation that failed

        Returns:
            GitHubError with appropriate context
        """
        status_code = exception.status if hasattr(exception, "status") else None
        
        # Extract rate limit info if available
        rate_limit_remaining = None
        rate_limit_reset = None
        
        if hasattr(exception, "headers"):
            rate_limit_remaining = exception.headers.get("X-RateLimit-Remaining")
            rate_limit_reset = exception.headers.get("X-RateLimit-Reset")

        log_with_context(
            logger,
            "error",
            "GitHub API error",
            operation=operation,
            status_code=status_code,
            rate_limit_remaining=rate_limit_remaining,
            error_message=str(exception),
        )

        # Determine if error is retryable
        retryable = status_code is None or status_code >= 500 or status_code == 429

        return GitHubError(
            f"GitHub API error during {operation}: {exception}",
            status_code=status_code,
            rate_limit_remaining=int(rate_limit_remaining) if rate_limit_remaining else None,
            rate_limit_reset=int(rate_limit_reset) if rate_limit_reset else None,
            retryable=retryable,
        )

    def _add_labels_safe(
        self,
        pr: Any,
        labels: list[str],
        repo: Any,
    ) -> None:
        """
        Add labels to PR, creating them if they don't exist.

        Args:
            pr: Pull request object
            labels: List of label names
            repo: Repository object
        """
        for label in labels:
            try:
                repo.get_label(label)
            except UnknownObjectException:
                # Create label if it doesn't exist
                try:
                    repo.create_label(
                        name=label,
                        color="0366d6",  # Blue color
                    )
                    log_with_context(
                        logger,
                        "debug",
                        "Created label",
                        label=label,
                    )
                except GithubException:
                    # Ignore label creation errors
                    pass

        try:
            pr.add_to_labels(*labels)
        except GithubException:
            log_with_context(
                logger,
                "warning",
                "Failed to add labels to PR",
                labels=labels,
            )

    def _generate_branch_name(self, failure: Failure) -> str:
        """
        Generate descriptive branch name.

        Args:
            failure: Vanta failure details

        Returns:
            Branch name like: terrafix/s3-block-public-access-1234

        Example:
            >>> branch = creator._generate_branch_name(failure)
        """
        test_slug = (
            failure.test_name.lower()
            .replace(" ", "-")
            .replace("_", "-")
            .replace("/", "-")[:50]
        )

        # Add short hash for uniqueness
        hash_suffix = hashlib.md5(failure.test_id.encode()).hexdigest()[:8]

        return f"terrafix/{test_slug}-{hash_suffix}"

    def _generate_commit_message(self, failure: Failure) -> str:
        """
        Generate conventional commit message.

        Args:
            failure: Vanta failure details

        Returns:
            Commit message following conventional commits format

        Example:
            >>> msg = creator._generate_commit_message(failure)
        """
        return f"""fix(compliance): {failure.test_name}

Automated fix generated by TerraFix to address compliance failure.

Test: {failure.test_name}
Framework: {failure.framework}
Severity: {failure.severity}
Resource: {failure.resource_arn}

This commit was automatically generated. Please review carefully
before merging.
"""

    def _generate_pr_title(self, failure: Failure) -> str:
        """
        Generate concise PR title.

        Args:
            failure: Vanta failure details

        Returns:
            PR title with severity indicator
        """
        severity_emoji = {
            "high": "🔴",
            "medium": "🟡",
            "low": "🟢",
        }
        emoji = severity_emoji.get(failure.severity, "⚪")

        return f"{emoji} [TerraFix] {failure.test_name}"

    def _generate_pr_body(
        self,
        failure: Failure,
        fix_metadata: RemediationFix,
        file_path: str,
    ) -> str:
        """
        Generate comprehensive PR description.

        Args:
            failure: Vanta failure details
            fix_metadata: Claude's fix explanation
            file_path: Modified file path

        Returns:
            Markdown-formatted PR body
        """
        # Truncate long JSON for readability
        current_state_json = json.dumps(failure.current_state, indent=2)
        required_state_json = json.dumps(failure.required_state, indent=2)

        if len(current_state_json) > 2000:
            current_state_json = current_state_json[:2000] + "\n... [truncated]"
        if len(required_state_json) > 2000:
            required_state_json = required_state_json[:2000] + "\n... [truncated]"

        return f"""## 🤖 Automated Compliance Remediation

This PR was automatically generated by TerraFix to address a compliance failure detected by Vanta.

### 📋 Compliance Failure Details

| Field | Value |
|-------|-------|
| **Test** | {failure.test_name} |
| **Framework** | {failure.framework} |
| **Severity** | {failure.severity.upper()} |
| **Resource** | `{failure.resource_arn}` |
| **Failed At** | {failure.failed_at} |

**Failure Reason**: {failure.failure_reason}

### 🔧 Changes Made

**Modified File**: `{file_path}`

**Changed Attributes**: {', '.join(f"`{attr}`" for attr in fix_metadata.changed_attributes)}

### 📝 Explanation

{fix_metadata.explanation}

### 🧠 Reasoning

{fix_metadata.reasoning}

### ⚠️ Review Checklist

Before merging this PR, please verify:

- [ ] The changes correctly address the compliance failure
- [ ] No breaking changes are introduced
- [ ] Resource names and identifiers are unchanged
- [ ] Existing tags and metadata are preserved
- [ ] The fix follows your team's Terraform conventions
- [ ] `terraform plan` shows expected changes only

### 🔄 Breaking Changes

{fix_metadata.breaking_changes}

### 📌 Additional Requirements

{fix_metadata.additional_requirements}

### 🤝 Review Confidence

AI Confidence: **{fix_metadata.confidence.upper()}**

{self._get_confidence_guidance(fix_metadata.confidence)}

---

<details>
<summary>View Current vs Required State</summary>

**Current State**:
```json
{current_state_json}
```

**Required State**:
```json
{required_state_json}
```

</details>

---

*Generated by [TerraFix](https://github.com/your-org/terrafix) - AI-Powered Terraform Compliance Remediation*
"""

    def _get_confidence_guidance(self, confidence: str) -> str:
        """
        Provide review guidance based on confidence level.

        Args:
            confidence: high/medium/low

        Returns:
            Guidance message
        """
        guidance = {
            "high": "✅ This fix has high confidence. Review should be straightforward.",
            "medium": "⚠️ This fix has medium confidence. Extra scrutiny recommended.",
            "low": "❌ This fix has low confidence. Thorough review required.",
        }
        return guidance.get(confidence, "")

    def _determine_labels(self, failure: Failure) -> list[str]:
        """
        Determine appropriate GitHub labels for PR.

        Args:
            failure: Vanta failure details

        Returns:
            List of label names to apply

        Example:
            >>> labels = creator._determine_labels(failure)
        """
        labels = ["compliance", "automated", "terrafix"]

        # Add severity label
        labels.append(f"severity:{failure.severity}")

        # Add framework label
        labels.append(f"framework:{failure.framework.lower()}")

        return labels

