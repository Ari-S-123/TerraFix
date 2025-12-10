"""
Terraform configuration validation.

Validates generated Terraform fixes using terraform fmt and terraform validate
commands before PR creation. This prevents creating PRs with invalid configurations
that would fail during terraform plan or apply.

Validation steps:
1. terraform fmt - Check/fix formatting
2. terraform init - Initialize provider plugins (required for validate)
3. terraform validate - Semantic validation of configuration

Usage:
    from terrafix.terraform_validator import TerraformValidator

    validator = TerraformValidator()
    result = validator.validate_configuration(
        content=fixed_config,
        filename="main.tf"
    )
    
    if result.is_valid:
        # Use result.formatted_content for PR
        pass
    else:
        # Log result.error_message
        pass
"""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from terrafix.errors import TerraformValidationError
from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """
    Result of Terraform validation.

    Attributes:
        is_valid: Whether the configuration passed validation
        formatted_content: Content after terraform fmt (if successful)
        error_message: Validation error message (if failed)
        warnings: List of non-fatal warnings from validation
    """

    is_valid: bool
    formatted_content: str | None = None
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)


class TerraformValidator:
    """
    Validates Terraform configurations using CLI tools.

    Runs terraform fmt for formatting and terraform validate for
    semantic validation. Operates in isolated temporary directories
    to prevent interference with other operations.

    Attributes:
        terraform_path: Path to terraform binary
    """

    def __init__(self, terraform_path: str = "terraform") -> None:
        """
        Initialize Terraform validator.

        Args:
            terraform_path: Path to terraform binary (default: "terraform" from PATH)

        Raises:
            TerraformValidationError: If terraform binary is not available

        Example:
            >>> validator = TerraformValidator()
            >>> # or with custom path
            >>> validator = TerraformValidator("/usr/local/bin/terraform")
        """
        self.terraform_path: str = terraform_path
        self._verify_terraform_available()

    def _verify_terraform_available(self) -> None:
        """
        Verify terraform CLI is available and functional.

        Raises:
            TerraformValidationError: If terraform is not available
        """
        try:
            result = subprocess.run(
                [self.terraform_path, "version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise TerraformValidationError(
                    f"Terraform version check failed: {result.stderr}",
                )

            version_line = result.stdout.split("\n")[0]
            log_with_context(
                logger,
                "info",
                "Terraform CLI verified",
                version=version_line,
            )

        except FileNotFoundError:
            log_with_context(
                logger,
                "error",
                "Terraform binary not found",
                path=self.terraform_path,
            )
            raise TerraformValidationError(
                f"Terraform binary not found at '{self.terraform_path}'",
            )

        except subprocess.TimeoutExpired:
            raise TerraformValidationError(
                "Terraform version check timed out",
            )

    def validate_configuration(
        self,
        content: str,
        filename: str = "main.tf",
        original_repo_path: Path | None = None,
    ) -> ValidationResult:
        """
        Validate a Terraform configuration.

        Creates an isolated temporary directory, writes the configuration,
        and runs terraform fmt followed by terraform validate.

        Args:
            content: Terraform configuration content (HCL)
            filename: Name for the temporary file
            original_repo_path: Path to original repo for provider context

        Returns:
            ValidationResult with validation status and formatted content

        Example:
            >>> result = validator.validate_configuration(
            ...     content='resource "aws_s3_bucket" "test" {}',
            ...     filename="s3.tf"
            ... )
            >>> if result.is_valid:
            ...     print(result.formatted_content)
        """
        with tempfile.TemporaryDirectory(prefix="terrafix_validate_") as tmpdir:
            tmppath = Path(tmpdir)

            # Write the configuration to validate
            config_file = tmppath / filename
            _ = config_file.write_text(content, encoding="utf-8")

            # Copy provider configuration if available
            if original_repo_path:
                self._copy_provider_files(original_repo_path, tmppath)

            # Step 1: Run terraform fmt
            fmt_result = self._run_terraform_fmt(tmppath, config_file)
            if not fmt_result.is_valid:
                return fmt_result

            # Step 2: Run terraform init (required for validate)
            init_result = self._run_terraform_init(tmppath)
            if not init_result.is_valid:
                # Init failure is a warning, not a hard failure
                # (might be missing provider credentials)
                log_with_context(
                    logger,
                    "warning",
                    "Terraform init failed, skipping validate",
                    error=init_result.error_message,
                )
                return ValidationResult(
                    is_valid=True,
                    formatted_content=fmt_result.formatted_content,
                    warnings=[f"Skipped validate: {init_result.error_message}"],
                )

            # Step 3: Run terraform validate
            validate_result = self._run_terraform_validate(tmppath)
            if not validate_result.is_valid:
                return validate_result

            return ValidationResult(
                is_valid=True,
                formatted_content=fmt_result.formatted_content,
                warnings=validate_result.warnings,
            )

    def _run_terraform_fmt(
        self,
        work_dir: Path,
        config_file: Path,
    ) -> ValidationResult:
        """
        Run terraform fmt on configuration.

        Args:
            work_dir: Working directory
            config_file: Path to configuration file

        Returns:
            ValidationResult with formatted content or error
        """
        try:
            result = subprocess.run(
                [self.terraform_path, "fmt", "-write=true", str(config_file)],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                log_with_context(
                    logger,
                    "error",
                    "Terraform fmt failed",
                    stderr=result.stderr,
                )
                return ValidationResult(
                    is_valid=False,
                    error_message=f"terraform fmt failed: {result.stderr}",
                )

            formatted_content = config_file.read_text(encoding="utf-8")

            log_with_context(
                logger,
                "debug",
                "Terraform fmt succeeded",
            )

            return ValidationResult(
                is_valid=True,
                formatted_content=formatted_content,
            )

        except subprocess.TimeoutExpired:
            return ValidationResult(
                is_valid=False,
                error_message="terraform fmt timed out after 60 seconds",
            )

    def _run_terraform_init(self, work_dir: Path) -> ValidationResult:
        """
        Run terraform init for provider installation.

        Args:
            work_dir: Working directory

        Returns:
            ValidationResult indicating init success/failure
        """
        try:
            result = subprocess.run(
                [
                    self.terraform_path,
                    "init",
                    "-backend=false",  # Don't configure backend
                    "-input=false",  # Non-interactive
                    "-no-color",
                ],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=300,  # Init can be slow for provider downloads
            )

            if result.returncode != 0:
                log_with_context(
                    logger,
                    "warning",
                    "Terraform init failed",
                    stderr=result.stderr[:500] if result.stderr else None,
                )
                return ValidationResult(
                    is_valid=False,
                    error_message=f"terraform init failed: {result.stderr[:200] if result.stderr else 'unknown error'}",
                )

            log_with_context(
                logger,
                "debug",
                "Terraform init succeeded",
            )

            return ValidationResult(is_valid=True)

        except subprocess.TimeoutExpired:
            return ValidationResult(
                is_valid=False,
                error_message="terraform init timed out after 300 seconds",
            )

    def _run_terraform_validate(self, work_dir: Path) -> ValidationResult:
        """
        Run terraform validate on configuration.

        Args:
            work_dir: Working directory

        Returns:
            ValidationResult indicating validation success/failure
        """
        try:
            result = subprocess.run(
                [self.terraform_path, "validate", "-json"],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )

            # Parse JSON output
            try:
                validation_output: dict[str, Any] = json.loads(result.stdout)
            except json.JSONDecodeError:
                # Fallback to non-JSON parsing
                if result.returncode != 0:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"terraform validate failed: {result.stderr}",
                    )
                return ValidationResult(is_valid=True)

            is_valid: bool = validation_output.get("valid", False)
            warnings: list[str] = []
            error_messages: list[str] = []

            diagnostics_list: list[dict[str, str]] = validation_output.get("diagnostics", [])
            for diagnostic in diagnostics_list:
                severity: str = diagnostic.get("severity", "error")
                summary: str = diagnostic.get("summary", "Unknown error")
                detail: str = diagnostic.get("detail", "")

                message = f"{summary}: {detail}" if detail else summary

                if severity == "warning":
                    warnings.append(message)
                else:
                    error_messages.append(message)

            if not is_valid:
                error_msg = "; ".join(error_messages) if error_messages else "Validation failed"
                log_with_context(
                    logger,
                    "error",
                    "Terraform validate failed",
                    errors=error_messages,
                    warnings=warnings,
                )
                return ValidationResult(
                    is_valid=False,
                    error_message=error_msg,
                    warnings=warnings,
                )

            log_with_context(
                logger,
                "debug",
                "Terraform validate succeeded",
                warnings=warnings,
            )

            return ValidationResult(
                is_valid=True,
                warnings=warnings,
            )

        except subprocess.TimeoutExpired:
            return ValidationResult(
                is_valid=False,
                error_message="terraform validate timed out after 120 seconds",
            )

    def _copy_provider_files(self, source: Path, dest: Path) -> None:
        """
        Copy provider and variable files for validation context.

        Copies configuration files that may be needed for proper
        validation, such as provider requirements and variable
        definitions.

        Args:
            source: Original repository path
            dest: Temporary validation directory
        """
        files_to_copy = [
            "versions.tf",
            "providers.tf",
            "terraform.tf",
            "variables.tf",
            ".terraform.lock.hcl",
        ]

        for filename in files_to_copy:
            source_file = source / filename
            if source_file.exists():
                try:
                    _ = shutil.copy2(source_file, dest / filename)
                    log_with_context(
                        logger,
                        "debug",
                        "Copied provider file",
                        filename=filename,
                    )
                except Exception as e:
                    log_with_context(
                        logger,
                        "warning",
                        "Failed to copy provider file",
                        filename=filename,
                        error=str(e),
                    )

    def format_only(self, content: str) -> str:
        """
        Run terraform fmt only (no validation).

        Useful for formatting content when full validation is not needed.

        Args:
            content: Terraform configuration content

        Returns:
            Formatted content (original if formatting fails)

        Example:
            >>> formatted = validator.format_only(config)
        """
        with tempfile.TemporaryDirectory(prefix="terrafix_fmt_") as tmpdir:
            tmppath = Path(tmpdir)
            config_file = tmppath / "main.tf"
            _ = config_file.write_text(content, encoding="utf-8")

            result = self._run_terraform_fmt(tmppath, config_file)

            if result.is_valid and result.formatted_content:
                return result.formatted_content
            return content

