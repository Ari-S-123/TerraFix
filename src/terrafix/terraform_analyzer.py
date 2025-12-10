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

from pathlib import Path
from typing import Any

import hcl2  # type: ignore[import-untyped]
from typing import cast

from terrafix.errors import TerraformParseError
from terrafix.logging_config import get_logger, log_with_context
from terrafix.resource_mappings import aws_to_terraform_type

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
        self.repo_path: Path = Path(repo_path)
        self.terraform_files: list[Path] = list(self.repo_path.rglob("*.tf"))
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
                parsed: dict[str, Any] = cast(dict[str, Any], hcl2.loads(content))

                self.parsed_configs[str(tf_file)] = {
                    "content": content,
                    "parsed": parsed,
                }

                resource_list: list[dict[str, Any]] = parsed.get("resource", [])
                log_with_context(
                    logger,
                    "debug",
                    "Parsed Terraform file",
                    file_path=str(tf_file),
                    resource_count=len(resource_list),
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

        # Map AWS resource type to Terraform type using comprehensive mapping
        tf_type = aws_to_terraform_type(resource_type)

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

        # If mapping is unknown, try fuzzy matching by ARN
        if tf_type is None:
            log_with_context(
                logger,
                "warning",
                "Unknown AWS resource type, attempting fuzzy match",
                aws_type=resource_type,
            )
            return self._fuzzy_find_by_arn(resource_arn)

        # Search all parsed configs for matching resource
        for file_path, config in self.parsed_configs.items():
            parsed_data: dict[str, Any] = cast(dict[str, Any], config["parsed"])

            # Look for matching resource blocks
            if "resource" in parsed_data:
                resources_list: list[dict[str, Any]] = cast(list[dict[str, Any]], parsed_data["resource"])
                for resources in resources_list:
                    for res_type, res_instances in resources.items():
                        if res_type == tf_type:
                            res_instances_dict: dict[str, Any] = cast(dict[str, Any], res_instances)
                            for res_name, res_config in res_instances_dict.items():
                                # Match by name or by inline ARN/ID
                                res_config_typed: dict[str, Any] = cast(dict[str, Any], res_config)
                                if res_name == resource_name or self._resource_matches_arn(
                                    res_config_typed, resource_arn
                                ):
                                    log_with_context(
                                        logger,
                                        "info",
                                        "Found resource in Terraform",
                                        file_path=file_path,
                                        resource_type=res_type,
                                        resource_name=res_name,
                                    )
                                    return (file_path, res_config_typed, res_name)

        log_with_context(
            logger,
            "warning",
            "Resource not found in Terraform",
            resource_arn=resource_arn,
            resource_type=resource_type,
            searched_files=len(self.parsed_configs),
        )

        return None

    def _fuzzy_find_by_arn(
        self,
        resource_arn: str,
    ) -> tuple[str, dict[str, Any], str] | None:
        """
        Attempt to find resource by ARN without knowing the Terraform type.

        Searches all resources for ARN or identifier matches. This is a
        fallback for resource types not in the mapping table.

        Args:
            resource_arn: AWS resource ARN

        Returns:
            Tuple of (file_path, resource_block, resource_name) or None
        """
        resource_name = self._extract_name_from_arn(resource_arn)

        for file_path, config in self.parsed_configs.items():
            parsed_data: dict[str, Any] = cast(dict[str, Any], config["parsed"])

            if "resource" not in parsed_data:
                continue

            resources_list: list[dict[str, Any]] = cast(list[dict[str, Any]], parsed_data["resource"])
            for resources in resources_list:
                for res_type, res_instances in resources.items():
                    res_instances_dict: dict[str, Any] = cast(dict[str, Any], res_instances)
                    for res_name, res_config in res_instances_dict.items():
                        res_cfg: dict[str, Any] = cast(dict[str, Any], res_config)
                        # Check if resource matches ARN
                        if self._resource_matches_arn(res_cfg, resource_arn):
                            log_with_context(
                                logger,
                                "info",
                                "Found resource via fuzzy match",
                                file_path=file_path,
                                resource_type=res_type,
                                resource_name=res_name,
                            )
                            return (file_path, res_cfg, res_name)

                        # Check if resource name matches
                        if res_name == resource_name:
                            log_with_context(
                                logger,
                                "info",
                                "Found resource by name match",
                                file_path=file_path,
                                resource_type=res_type,
                                resource_name=res_name,
                            )
                            return (file_path, res_cfg, res_name)

        return None

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
            config_bucket: str | list[str] = resource_config["bucket"]

            # Handle both string and list values
            if isinstance(config_bucket, list):
                bucket_str: str = str(config_bucket[0]) if config_bucket else ""
            else:
                bucket_str = str(config_bucket)

            return bucket_str == bucket_name

        # Check for name attribute
        if "name" in resource_config:
            extracted_name = self._extract_name_from_arn(arn)
            config_name: str | list[str] = resource_config["name"]

            if isinstance(config_name, list):
                name_str: str = str(config_name[0]) if config_name else ""
            else:
                name_str = str(config_name)

            return name_str == extracted_name

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
        config_entry = self.parsed_configs.get(file_path, {})
        parsed_cfg: dict[str, Any] = cast(dict[str, Any], config_entry.get("parsed", {}))

        provider_list: list[dict[str, Any]] = cast(list[dict[str, Any]], parsed_cfg.get("provider", []))
        variable_list: list[dict[str, Any]] = cast(list[dict[str, Any]], parsed_cfg.get("variable", []))
        output_list: list[dict[str, Any]] = cast(list[dict[str, Any]], parsed_cfg.get("output", []))
        module_list: list[dict[str, Any]] = cast(list[dict[str, Any]], parsed_cfg.get("module", []))

        context: dict[str, Any] = {
            "provider": provider_list,
            "variable": variable_list,
            "output": output_list,
            "module": module_list,
        }

        log_with_context(
            logger,
            "debug",
            "Extracted module context",
            file_path=file_path,
            provider_count=len(provider_list),
            variable_count=len(variable_list),
            output_count=len(output_list),
            module_count=len(module_list),
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

        return str(config["content"])

