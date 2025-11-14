"""
Terraform configuration parser and analyzer.

This module provides parsing and analysis of Terraform HCL configurations
to locate resources that correspond to Vanta compliance failures. It uses
python-hcl2 to parse .tf files and provides resource matching by AWS ARN.

The analyzer scans a cloned repository for all .tf files, parses them,
and provides APIs to locate specific resources and extract module context.

Usage:
    from terrafix.terraform_analyzer import TerraformAnalyzer

    analyzer = TerraformAnalyzer("/path/to/repo")
    result = analyzer.find_resource_by_arn(
        "arn:aws:s3:::my-bucket",
        "AWS::S3::Bucket"
    )
    if result:
        file_path, resource_block, resource_name = result
        print(f"Found resource in {file_path}")
"""

import re
from pathlib import Path
from typing import Any

import hcl2

from terrafix.errors import ResourceNotFoundError, TerraformParseError
from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


class TerraformAnalyzer:
    """
    Analyzes Terraform configurations to locate and understand resources.

    The analyzer parses all .tf files in a repository and provides methods
    to locate resources by ARN and extract module context. It handles parsing
    errors gracefully by skipping unparsable files.

    Attributes:
        repo_path: Path to cloned Terraform repository
        terraform_files: List of .tf file paths found
        parsed_configs: Dict mapping file paths to parsed HCL
    """

    def __init__(self, repo_path: str) -> None:
        """
        Initialize Terraform analyzer.

        Scans the repository for .tf files and parses them immediately.
        Parsing errors are logged as warnings but don't fail initialization.

        Args:
            repo_path: Path to repository containing Terraform files

        Example:
            >>> analyzer = TerraformAnalyzer("/tmp/terraform-repo")
            >>> print(f"Found {len(analyzer.terraform_files)} files")
        """
        self.repo_path = Path(repo_path)
        self.terraform_files = list(self.repo_path.rglob("*.tf"))
        self.parsed_configs: dict[str, dict[str, Any]] = {}

        log_with_context(
            logger,
            "info",
            "Initializing Terraform analyzer",
            repo_path=str(self.repo_path),
            file_count=len(self.terraform_files),
        )

        self._parse_all_files()

    def _parse_all_files(self) -> None:
        """
        Parse all Terraform files in the repository.

        Stores parsed configurations in self.parsed_configs with file
        paths as keys. Files that fail to parse are logged as warnings
        and skipped.

        Raises:
            TerraformParseError: Not raised directly, but logged for each failure
        """
        for tf_file in self.terraform_files:
            try:
                with open(tf_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # python-hcl2 parses Terraform HCL
                parsed = hcl2.loads(content)

                self.parsed_configs[str(tf_file)] = {
                    "content": content,
                    "parsed": parsed,
                }

                log_with_context(
                    logger,
                    "debug",
                    "Parsed Terraform file",
                    file_path=str(tf_file),
                    resource_count=len(parsed.get("resource", [])),
                )

            except Exception as e:
                # Log but continue - some files may have syntax errors
                log_with_context(
                    logger,
                    "warning",
                    "Failed to parse Terraform file",
                    file_path=str(tf_file),
                    error=str(e),
                )

        log_with_context(
            logger,
            "info",
            "Completed Terraform file parsing",
            total_files=len(self.terraform_files),
            parsed_files=len(self.parsed_configs),
            failed_files=len(self.terraform_files) - len(self.parsed_configs),
        )

    def find_resource_by_arn(
        self,
        resource_arn: str,
        resource_type: str,
    ) -> tuple[str, dict[str, Any], str] | None:
        """
        Locate a Terraform resource block by AWS ARN.

        Searches all parsed Terraform files for a resource matching the
        given ARN. Returns the file path, resource block, and resource name.

        Args:
            resource_arn: AWS resource ARN
            resource_type: AWS resource type (AWS::S3::Bucket, etc.)

        Returns:
            Tuple of (file_path, resource_block, resource_name) or None if not found

        Raises:
            ResourceNotFoundError: If resource cannot be located

        Example:
            >>> result = analyzer.find_resource_by_arn(
            ...     "arn:aws:s3:::my-bucket",
            ...     "AWS::S3::Bucket"
            ... )
            >>> if result:
            ...     file_path, block, name = result
        """
        log_with_context(
            logger,
            "info",
            "Searching for resource by ARN",
            resource_arn=resource_arn,
            resource_type=resource_type,
        )

        # Map AWS resource type to Terraform type
        tf_type = self._aws_to_terraform_type(resource_type)

        # Extract resource name from ARN
        resource_name = self._extract_name_from_arn(resource_arn)

        log_with_context(
            logger,
            "debug",
            "Mapped AWS type to Terraform type",
            aws_type=resource_type,
            terraform_type=tf_type,
            extracted_name=resource_name,
        )

        # Search all parsed configs
        for file_path, config in self.parsed_configs.items():
            parsed = config["parsed"]

            # Look for matching resource blocks
            if "resource" in parsed:
                for resources in parsed["resource"]:
                    for res_type, res_instances in resources.items():
                        if res_type == tf_type:
                            for res_name, res_config in res_instances.items():
                                # Match by name or by inline ARN/ID
                                if res_name == resource_name or self._resource_matches_arn(
                                    res_config, resource_arn
                                ):
                                    log_with_context(
                                        logger,
                                        "info",
                                        "Found resource in Terraform",
                                        file_path=file_path,
                                        resource_type=res_type,
                                        resource_name=res_name,
                                    )
                                    return (file_path, res_config, res_name)

        log_with_context(
            logger,
            "warning",
            "Resource not found in Terraform",
            resource_arn=resource_arn,
            resource_type=resource_type,
            searched_files=len(self.parsed_configs),
        )

        return None

    def _aws_to_terraform_type(self, aws_type: str) -> str:
        """
        Convert AWS CloudFormation type to Terraform type.

        Maps AWS resource types (AWS::Service::Resource) to Terraform
        resource types (aws_service_resource).

        Args:
            aws_type: CloudFormation resource type

        Returns:
            Terraform resource type

        Examples:
            >>> analyzer._aws_to_terraform_type("AWS::S3::Bucket")
            "aws_s3_bucket"
            >>> analyzer._aws_to_terraform_type("AWS::IAM::Role")
            "aws_iam_role"
        """
        # Remove AWS:: prefix and convert to lowercase snake_case
        parts = aws_type.replace("AWS::", "").split("::")
        return "aws_" + "_".join(p.lower() for p in parts)

    def _extract_name_from_arn(self, arn: str) -> str:
        """
        Extract resource name from ARN.

        Handles various ARN formats for different AWS services.

        Args:
            arn: AWS ARN

        Returns:
            Resource name extracted from ARN

        Examples:
            >>> analyzer._extract_name_from_arn("arn:aws:s3:::bucket-name")
            "bucket-name"
            >>> analyzer._extract_name_from_arn("arn:aws:iam::123456:role/RoleName")
            "RoleName"
        """
        # S3 bucket ARN pattern
        if ":s3:::" in arn:
            return arn.split(":::")[-1].split("/")[0]

        # Most other ARNs
        if "/" in arn:
            return arn.split("/")[-1]

        # Fallback: return last component
        return arn.split(":")[-1]

    def _resource_matches_arn(
        self,
        resource_config: dict[str, Any],
        arn: str,
    ) -> bool:
        """
        Check if Terraform resource configuration matches ARN.

        Checks various fields in the resource configuration to determine
        if it matches the given ARN. This handles cases where the resource
        name doesn't match but inline attributes do.

        Args:
            resource_config: Terraform resource configuration block
            arn: AWS ARN to match against

        Returns:
            True if resource matches ARN

        Example:
            >>> config = {"arn": "arn:aws:s3:::bucket"}
            >>> analyzer._resource_matches_arn(config, "arn:aws:s3:::bucket")
            True
        """
        # Check for explicit ARN in config
        if "arn" in resource_config:
            return resource_config["arn"] == arn

        # Check for bucket name in S3 resources
        if "bucket" in resource_config:
            bucket_name = self._extract_name_from_arn(arn)
            config_bucket = resource_config["bucket"]

            # Handle both string and list values
            if isinstance(config_bucket, list):
                config_bucket = config_bucket[0] if config_bucket else ""

            return config_bucket == bucket_name

        # Check for name attribute
        if "name" in resource_config:
            extracted_name = self._extract_name_from_arn(arn)
            config_name = resource_config["name"]

            if isinstance(config_name, list):
                config_name = config_name[0] if config_name else ""

            return config_name == extracted_name

        return False

    def get_module_context(self, file_path: str) -> dict[str, Any]:
        """
        Get module-level context for a file.

        Extracts provider configuration, variables, outputs, and module
        calls from the Terraform file to provide context for fix generation.

        Args:
            file_path: Path to Terraform file

        Returns:
            Dict containing:
            - provider: Provider configuration blocks
            - variable: Input variable definitions
            - output: Output definitions
            - module: Other module references

        Example:
            >>> context = analyzer.get_module_context("/path/to/s3.tf")
            >>> print(context["provider"])
        """
        parsed = self.parsed_configs.get(file_path, {}).get("parsed", {})

        context = {
            "provider": parsed.get("provider", []),
            "variable": parsed.get("variable", []),
            "output": parsed.get("output", []),
            "module": parsed.get("module", []),
        }

        log_with_context(
            logger,
            "debug",
            "Extracted module context",
            file_path=file_path,
            provider_count=len(context["provider"]),
            variable_count=len(context["variable"]),
            output_count=len(context["output"]),
            module_count=len(context["module"]),
        )

        return context

    def get_file_content(self, file_path: str) -> str:
        """
        Get raw file content for a parsed Terraform file.

        Args:
            file_path: Path to Terraform file

        Returns:
            Raw file content as string

        Raises:
            TerraformParseError: If file was not successfully parsed

        Example:
            >>> content = analyzer.get_file_content("/path/to/s3.tf")
        """
        config = self.parsed_configs.get(file_path)
        if not config:
            raise TerraformParseError(
                f"File {file_path} was not successfully parsed",
                file_path=file_path,
            )

        return config["content"]

