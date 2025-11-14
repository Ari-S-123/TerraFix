"""
Orchestration and processing pipeline for compliance failure remediation.

This module coordinates the end-to-end remediation pipeline, from failure
detection through PR creation. It handles deduplication, repository cloning,
Terraform analysis, fix generation, and GitHub PR creation.

The orchestrator implements retry logic with exponential backoff for transient
failures and graceful error handling for permanent failures.

Usage:
    from terrafix.orchestrator import process_failure
    from terrafix.config import get_settings

    settings = get_settings()
    # ... initialize clients ...

    result = process_failure(
        failure=failure,
        config=settings,
        state_store=store,
        vanta=vanta_client,
        generator=generator,
        gh=gh_creator
    )
"""

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from terrafix.config import Settings
from terrafix.errors import (
    BedrockError,
    GitHubError,
    ResourceNotFoundError,
    TerraFixError,
    TerraformParseError,
    VantaApiError,
)
from terrafix.github_pr_creator import GitHubPRCreator
from terrafix.logging_config import LogContext, get_logger, log_with_context
from terrafix.remediation_generator import TerraformRemediationGenerator
from terrafix.state_store import StateStore
from terrafix.terraform_analyzer import TerraformAnalyzer
from terrafix.vanta_client import Failure, VantaClient

logger = get_logger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60


class ProcessingResult:
    """
    Result of processing a single failure.

    Attributes:
        success: Whether processing succeeded
        failure_hash: Hash of the processed failure
        pr_url: GitHub PR URL if successful
        error: Error message if failed
        skipped: Whether failure was skipped (duplicate)
    """

    def __init__(
        self,
        success: bool,
        failure_hash: str,
        pr_url: str | None = None,
        error: str | None = None,
        skipped: bool = False,
    ) -> None:
        """Initialize processing result."""
        self.success = success
        self.failure_hash = failure_hash
        self.pr_url = pr_url
        self.error = error
        self.skipped = skipped


def process_failure(
    failure: Failure,
    config: Settings,
    state_store: StateStore,
    vanta: VantaClient,
    generator: TerraformRemediationGenerator,
    gh: GitHubPRCreator,
) -> ProcessingResult:
    """
    Process a single compliance failure end-to-end.

    This is the main orchestration function that coordinates:
    1. Deduplication check
    2. Repository cloning
    3. Terraform analysis
    4. Fix generation via Bedrock
    5. Validation and formatting
    6. GitHub PR creation
    7. State tracking

    Args:
        failure: Vanta compliance failure to process
        config: Application settings
        state_store: SQLite state store for deduplication
        vanta: Vanta API client (unused but kept for signature)
        generator: Bedrock remediation generator
        gh: GitHub PR creator

    Returns:
        ProcessingResult with success status and details

    Example:
        >>> result = process_failure(
        ...     failure=failure,
        ...     config=settings,
        ...     state_store=store,
        ...     vanta=vanta_client,
        ...     generator=generator,
        ...     gh=gh_creator
        ... )
        >>> if result.success:
        ...     print(f"Created PR: {result.pr_url}")
    """
    # Generate correlation ID for this processing run
    with LogContext() as correlation_id:
        log_with_context(
            logger,
            "info",
            "Starting failure processing",
            test_id=failure.test_id,
            resource_arn=failure.resource_arn,
            severity=failure.severity,
            correlation_id=correlation_id,
        )

        # Generate failure hash for deduplication
        failure_hash = vanta.generate_failure_hash(failure)

        # Check if already processed
        if state_store.is_already_processed(failure_hash):
            log_with_context(
                logger,
                "info",
                "Failure already processed, skipping",
                failure_hash=failure_hash,
                test_id=failure.test_id,
            )
            return ProcessingResult(
                success=True,
                failure_hash=failure_hash,
                skipped=True,
            )

        # Mark as in progress
        try:
            state_store.mark_in_progress(
                failure_hash,
                failure.test_id,
                failure.resource_arn,
            )
        except Exception as e:
            log_with_context(
                logger,
                "error",
                "Failed to mark as in progress",
                failure_hash=failure_hash,
                error=str(e),
            )
            # Continue anyway - state update failure shouldn't block processing

        # Process the failure with retry logic
        try:
            pr_url = _process_failure_with_retry(
                failure=failure,
                config=config,
                generator=generator,
                gh=gh,
            )

            # Mark as successfully processed
            state_store.mark_processed(failure_hash, pr_url)

            log_with_context(
                logger,
                "info",
                "Successfully processed failure",
                failure_hash=failure_hash,
                pr_url=pr_url,
            )

            return ProcessingResult(
                success=True,
                failure_hash=failure_hash,
                pr_url=pr_url,
            )

        except Exception as e:
            error_msg = str(e)

            log_with_context(
                logger,
                "error",
                "Failed to process failure",
                failure_hash=failure_hash,
                error=error_msg,
                error_type=type(e).__name__,
            )

            # Mark as failed in state store
            try:
                state_store.mark_failed(failure_hash, error_msg)
            except Exception as state_error:
                log_with_context(
                    logger,
                    "warning",
                    "Failed to mark as failed in state store",
                    error=str(state_error),
                )

            return ProcessingResult(
                success=False,
                failure_hash=failure_hash,
                error=error_msg,
            )


def _process_failure_with_retry(
    failure: Failure,
    config: Settings,
    generator: TerraformRemediationGenerator,
    gh: GitHubPRCreator,
) -> str:
    """
    Process failure with retry logic for transient errors.

    Args:
        failure: Vanta compliance failure
        config: Application settings
        generator: Bedrock remediation generator
        gh: GitHub PR creator

    Returns:
        GitHub PR URL

    Raises:
        TerraFixError: If processing fails after retries
    """
    last_exception: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            return _process_failure_once(
                failure=failure,
                config=config,
                generator=generator,
                gh=gh,
            )

        except (VantaApiError, BedrockError, GitHubError) as e:
            # Check if error is retryable
            if not e.retryable or attempt >= MAX_RETRIES - 1:
                raise

            # Calculate backoff with exponential increase and jitter
            backoff = min(
                INITIAL_BACKOFF_SECONDS * (2**attempt),
                MAX_BACKOFF_SECONDS,
            )

            log_with_context(
                logger,
                "warning",
                "Transient error, retrying",
                attempt=attempt + 1,
                max_retries=MAX_RETRIES,
                backoff_seconds=backoff,
                error=str(e),
            )

            time.sleep(backoff)
            last_exception = e

        except (TerraformParseError, ResourceNotFoundError) as e:
            # These are permanent errors, don't retry
            log_with_context(
                logger,
                "error",
                "Permanent error, not retrying",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

        except Exception as e:
            # Unknown error, log and raise
            log_with_context(
                logger,
                "error",
                "Unexpected error during processing",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    # Should never reach here, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry logic failed unexpectedly")


def _process_failure_once(
    failure: Failure,
    config: Settings,
    generator: TerraformRemediationGenerator,
    gh: GitHubPRCreator,
) -> str:
    """
    Process failure once (single attempt).

    Args:
        failure: Vanta compliance failure
        config: Application settings
        generator: Bedrock remediation generator
        gh: GitHub PR creator

    Returns:
        GitHub PR URL

    Raises:
        TerraFixError: If any step fails
    """
    # Determine target repository
    repo_full_name = config.get_repo_for_resource(failure.resource_arn)
    if not repo_full_name:
        raise ResourceNotFoundError(
            f"No repository mapping found for {failure.resource_arn}",
            resource_arn=failure.resource_arn,
        )

    log_with_context(
        logger,
        "info",
        "Mapped resource to repository",
        resource_arn=failure.resource_arn,
        repo=repo_full_name,
    )

    # Clone repository into temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir) / "repo"

        log_with_context(
            logger,
            "info",
            "Cloning repository",
            repo=repo_full_name,
            path=str(repo_path),
        )

        _clone_repository(repo_full_name, repo_path, config.github_token)

        # Navigate to Terraform directory if specified
        terraform_path = repo_path / config.terraform_path
        if not terraform_path.exists():
            raise ResourceNotFoundError(
                f"Terraform path {config.terraform_path} not found in repository",
            )

        # Analyze Terraform configuration
        log_with_context(
            logger,
            "info",
            "Analyzing Terraform configuration",
            terraform_path=str(terraform_path),
        )

        analyzer = TerraformAnalyzer(str(terraform_path))

        # Find resource by ARN
        resource_result = analyzer.find_resource_by_arn(
            failure.resource_arn,
            failure.resource_type,
        )

        if not resource_result:
            raise ResourceNotFoundError(
                f"Resource {failure.resource_arn} not found in Terraform",
                resource_arn=failure.resource_arn,
                resource_type=failure.resource_type,
                searched_files=len(analyzer.terraform_files),
            )

        file_path, resource_block, resource_name = resource_result

        log_with_context(
            logger,
            "info",
            "Found resource in Terraform",
            file_path=file_path,
            resource_name=resource_name,
        )

        # Get module context and current file content
        module_context = analyzer.get_module_context(file_path)
        current_config = analyzer.get_file_content(file_path)

        # Generate fix using Bedrock
        log_with_context(
            logger,
            "info",
            "Generating fix via Bedrock",
            test_id=failure.test_id,
        )

        fix = generator.generate_fix(
            failure=failure,
            current_config=current_config,
            resource_block=resource_block,
            module_context=module_context,
        )

        log_with_context(
            logger,
            "info",
            "Generated fix",
            confidence=fix.confidence,
            changed_attributes=fix.changed_attributes,
        )

        # Validate fixed config (basic checks)
        if not fix.fixed_config or not fix.fixed_config.strip():
            raise TerraFixError(
                "Generated fix is empty",
                retryable=False,
            )

        # Optionally run terraform fmt on the fixed config
        formatted_config = _format_terraform(fix.fixed_config)

        # Calculate relative file path from repo root
        relative_file_path = Path(file_path).relative_to(repo_path)

        # Create PR
        log_with_context(
            logger,
            "info",
            "Creating GitHub PR",
            repo=repo_full_name,
            file_path=str(relative_file_path),
        )

        pr_url = gh.create_remediation_pr(
            repo_full_name=repo_full_name,
            file_path=str(relative_file_path),
            new_content=formatted_config,
            failure=failure,
            fix_metadata=fix,
        )

        if not pr_url:
            raise GitHubError(
                "Failed to create PR (duplicate branch)",
                retryable=False,
            )

        return pr_url


def _clone_repository(
    repo_full_name: str,
    target_path: Path,
    github_token: str,
) -> None:
    """
    Clone GitHub repository using git CLI.

    Args:
        repo_full_name: Repository (owner/repo)
        target_path: Local path to clone into
        github_token: GitHub token for authentication

    Raises:
        GitHubError: If clone fails
    """
    # Use HTTPS with token authentication
    clone_url = f"https://x-access-token:{github_token}@github.com/{repo_full_name}.git"

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(target_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        log_with_context(
            logger,
            "info",
            "Successfully cloned repository",
            repo=repo_full_name,
        )

    except subprocess.CalledProcessError as e:
        log_with_context(
            logger,
            "error",
            "Failed to clone repository",
            repo=repo_full_name,
            error=e.stderr,
        )
        raise GitHubError(
            f"Failed to clone repository: {e.stderr}",
            retryable=True,
        ) from e

    except subprocess.TimeoutExpired as e:
        log_with_context(
            logger,
            "error",
            "Repository clone timed out",
            repo=repo_full_name,
        )
        raise GitHubError(
            "Repository clone timed out",
            retryable=True,
        ) from e

    except FileNotFoundError as e:
        log_with_context(
            logger,
            "error",
            "Git command not found",
        )
        raise GitHubError(
            "Git command not found. Please install git.",
            retryable=False,
        ) from e


def _format_terraform(config: str) -> str:
    """
    Format Terraform configuration using terraform fmt.

    Args:
        config: Terraform configuration string

    Returns:
        Formatted Terraform configuration

    Note:
        If terraform is not available or formatting fails, returns
        the original config unchanged.
    """
    try:
        # Write config to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".tf",
            delete=False,
        ) as f:
            f.write(config)
            temp_path = f.name

        try:
            # Run terraform fmt
            result = subprocess.run(
                ["terraform", "fmt", temp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Read formatted content
            with open(temp_path, "r") as f:
                formatted = f.read()

            log_with_context(
                logger,
                "debug",
                "Formatted Terraform configuration",
            )

            return formatted

        finally:
            # Clean up temporary file
            Path(temp_path).unlink(missing_ok=True)

    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        log_with_context(
            logger,
            "warning",
            "Terraform fmt not available or failed, using unformatted config",
        )
        return config

    except Exception as e:
        log_with_context(
            logger,
            "warning",
            "Failed to format Terraform config",
            error=str(e),
        )
        return config

