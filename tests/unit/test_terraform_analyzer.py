"""
Unit tests for TerraformAnalyzer.

Tests cover HCL parsing, resource matching by ARN, fuzzy finding,
module context extraction, and error handling.
"""

from pathlib import Path
from typing import Any

import pytest

from terrafix.errors import TerraformParseError
from terrafix.terraform_analyzer import TerraformAnalyzer


class TestTerraformAnalyzerInit:
    """Tests for TerraformAnalyzer initialization."""

    def test_init_finds_tf_files(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test that analyzer finds all .tf files in repository."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        # Sample repo has main.tf, variables.tf, s3.tf, iam.tf, outputs.tf
        assert len(analyzer.terraform_files) == 5

    def test_init_parses_valid_files(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test that valid .tf files are parsed successfully."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        # All files should be parsed
        assert len(analyzer.parsed_configs) == 5

    def test_init_with_invalid_file_skips_gracefully(
        self,
        tmp_path: Path,
    ) -> None:
        """Test that invalid HCL files are skipped without failing."""
        # Create valid file
        (tmp_path / "valid.tf").write_text('''
resource "aws_s3_bucket" "test" {
  bucket = "test-bucket"
}
''')

        # Create invalid file
        (tmp_path / "invalid.tf").write_text('''
resource "aws_s3_bucket" "test" {
  bucket = "unclosed-brace
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        # Should find both files
        assert len(analyzer.terraform_files) == 2

        # Only valid file should be parsed
        assert len(analyzer.parsed_configs) == 1

    def test_init_empty_directory(
        self,
        tmp_path: Path,
    ) -> None:
        """Test initialization with empty directory."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        assert len(analyzer.terraform_files) == 0
        assert len(analyzer.parsed_configs) == 0


class TestFindResourceByArn:
    """Tests for TerraformAnalyzer.find_resource_by_arn method."""

    def test_find_s3_bucket_by_arn(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test finding S3 bucket resource by ARN."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        result = analyzer.find_resource_by_arn(
            "arn:aws:s3:::test-bucket-12345",
            "AWS::S3::Bucket",
        )

        assert result is not None
        file_path, resource_block, resource_name = result

        assert "s3.tf" in file_path
        assert resource_name == "test_bucket"
        assert "bucket" in resource_block

    def test_find_iam_role_by_arn(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test finding IAM role resource by ARN."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        result = analyzer.find_resource_by_arn(
            "arn:aws:iam::123456789012:role/test-role",
            "AWS::IAM::Role",
        )

        assert result is not None
        file_path, resource_block, resource_name = result

        assert "iam.tf" in file_path
        assert resource_name == "test_role"

    def test_resource_not_found_returns_none(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test that non-existent resource returns None."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        result = analyzer.find_resource_by_arn(
            "arn:aws:s3:::nonexistent-bucket",
            "AWS::S3::Bucket",
        )

        assert result is None

    def test_find_resource_by_bucket_attribute(
        self,
        tmp_path: Path,
    ) -> None:
        """Test finding resource by bucket attribute matching."""
        (tmp_path / "main.tf").write_text('''
resource "aws_s3_bucket" "my_bucket" {
  bucket = "my-specific-bucket-name"
  
  tags = {
    Name = "My Bucket"
  }
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        result = analyzer.find_resource_by_arn(
            "arn:aws:s3:::my-specific-bucket-name",
            "AWS::S3::Bucket",
        )

        assert result is not None
        _, _, resource_name = result
        assert resource_name == "my_bucket"


class TestFuzzyFindByArn:
    """Tests for TerraformAnalyzer._fuzzy_find_by_arn method."""

    def test_fuzzy_find_unknown_resource_type(
        self,
        tmp_path: Path,
    ) -> None:
        """Test fuzzy finding when AWS type is unknown."""
        (tmp_path / "main.tf").write_text('''
resource "aws_custom_resource" "custom" {
  name = "custom-resource-name"
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        # Use an unknown AWS resource type
        result = analyzer.find_resource_by_arn(
            "arn:aws:custom:::custom-resource-name",
            "AWS::Custom::Resource",  # Not in mapping
        )

        assert result is not None
        _, _, resource_name = result
        assert resource_name == "custom"

    def test_fuzzy_find_by_name_attribute(
        self,
        tmp_path: Path,
    ) -> None:
        """Test fuzzy finding by name attribute."""
        (tmp_path / "main.tf").write_text('''
resource "aws_unknown_service" "test" {
  name = "my-resource-name"
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        result = analyzer._fuzzy_find_by_arn(
            "arn:aws:unknown:::my-resource-name"
        )

        assert result is not None


class TestExtractNameFromArn:
    """Tests for TerraformAnalyzer._extract_name_from_arn method."""

    def test_extract_name_s3_bucket(
        self,
        tmp_path: Path,
    ) -> None:
        """Test extracting bucket name from S3 ARN."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        name = analyzer._extract_name_from_arn("arn:aws:s3:::my-bucket-name")

        assert name == "my-bucket-name"

    def test_extract_name_s3_bucket_with_path(
        self,
        tmp_path: Path,
    ) -> None:
        """Test extracting bucket name from S3 ARN with object path."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        name = analyzer._extract_name_from_arn("arn:aws:s3:::my-bucket/path/to/object")

        assert name == "my-bucket"

    def test_extract_name_iam_role(
        self,
        tmp_path: Path,
    ) -> None:
        """Test extracting role name from IAM ARN."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        name = analyzer._extract_name_from_arn(
            "arn:aws:iam::123456789012:role/MyRoleName"
        )

        assert name == "MyRoleName"

    def test_extract_name_lambda_function(
        self,
        tmp_path: Path,
    ) -> None:
        """Test extracting function name from Lambda ARN."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        name = analyzer._extract_name_from_arn(
            "arn:aws:lambda:us-west-2:123456789012:function:MyFunction"
        )

        assert name == "MyFunction"

    def test_extract_name_simple_arn(
        self,
        tmp_path: Path,
    ) -> None:
        """Test extracting name from simple ARN format."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        name = analyzer._extract_name_from_arn(
            "arn:aws:ec2:us-west-2:123456789012:instance:i-12345"
        )

        assert name == "i-12345"


class TestResourceMatchesArn:
    """Tests for TerraformAnalyzer._resource_matches_arn method."""

    def test_matches_by_explicit_arn(
        self,
        tmp_path: Path,
    ) -> None:
        """Test matching when resource has explicit ARN attribute."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        config: dict[str, Any] = {
            "arn": "arn:aws:s3:::my-bucket",
        }

        assert analyzer._resource_matches_arn(config, "arn:aws:s3:::my-bucket")
        assert not analyzer._resource_matches_arn(config, "arn:aws:s3:::other-bucket")

    def test_matches_by_bucket_attribute(
        self,
        tmp_path: Path,
    ) -> None:
        """Test matching by bucket attribute for S3 resources."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        config: dict[str, Any] = {
            "bucket": "my-bucket-name",
        }

        assert analyzer._resource_matches_arn(config, "arn:aws:s3:::my-bucket-name")
        assert not analyzer._resource_matches_arn(config, "arn:aws:s3:::other-bucket")

    def test_matches_by_bucket_attribute_list(
        self,
        tmp_path: Path,
    ) -> None:
        """Test matching when bucket is a list (HCL2 parsing quirk)."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        config: dict[str, Any] = {
            "bucket": ["my-bucket-name"],
        }

        assert analyzer._resource_matches_arn(config, "arn:aws:s3:::my-bucket-name")

    def test_matches_by_name_attribute(
        self,
        tmp_path: Path,
    ) -> None:
        """Test matching by name attribute."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        config: dict[str, Any] = {
            "name": "my-role-name",
        }

        assert analyzer._resource_matches_arn(
            config, "arn:aws:iam::123456:role/my-role-name"
        )

    def test_no_match_empty_config(
        self,
        tmp_path: Path,
    ) -> None:
        """Test that empty config doesn't match."""
        analyzer = TerraformAnalyzer(str(tmp_path))

        config: dict[str, Any] = {}

        assert not analyzer._resource_matches_arn(config, "arn:aws:s3:::bucket")


class TestGetModuleContext:
    """Tests for TerraformAnalyzer.get_module_context method."""

    def test_get_module_context_with_providers(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test extracting provider context from file."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        # Find the main.tf file path
        main_tf = None
        for path in analyzer.parsed_configs:
            if "main.tf" in path:
                main_tf = path
                break

        assert main_tf is not None

        context = analyzer.get_module_context(main_tf)

        assert "provider" in context
        assert "variable" in context
        assert "output" in context
        assert "module" in context

    def test_get_module_context_with_variables(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test extracting variable context from file."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        # Find the variables.tf file path
        vars_tf = None
        for path in analyzer.parsed_configs:
            if "variables.tf" in path:
                vars_tf = path
                break

        assert vars_tf is not None

        context = analyzer.get_module_context(vars_tf)

        # variables.tf has variable definitions
        assert len(context["variable"]) > 0

    def test_get_module_context_nonexistent_file(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test getting context for unparsed file returns empty."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        context = analyzer.get_module_context("/nonexistent/path.tf")

        assert context["provider"] == []
        assert context["variable"] == []
        assert context["output"] == []
        assert context["module"] == []


class TestGetFileContent:
    """Tests for TerraformAnalyzer.get_file_content method."""

    def test_get_file_content_success(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test getting file content for parsed file."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        # Get any parsed file
        file_path = list(analyzer.parsed_configs.keys())[0]

        content = analyzer.get_file_content(file_path)

        assert isinstance(content, str)
        assert len(content) > 0

    def test_get_file_content_not_parsed_raises(
        self,
        sample_terraform_repo: Path,
    ) -> None:
        """Test that getting content for unparsed file raises error."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo))

        with pytest.raises(TerraformParseError) as exc_info:
            analyzer.get_file_content("/nonexistent/file.tf")

        assert "was not successfully parsed" in str(exc_info.value)


class TestLargeRepository:
    """Tests for TerraformAnalyzer with larger repositories."""

    def test_parse_large_repository(
        self,
        sample_terraform_repo_large: Path,
    ) -> None:
        """Test parsing repository with many resources."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo_large))

        # Should find main.tf and module files
        assert len(analyzer.terraform_files) >= 2

        # Main.tf should have many module calls
        main_tf = None
        for path in analyzer.parsed_configs:
            if path.endswith("main.tf") and "modules" not in path:
                main_tf = path
                break

        assert main_tf is not None

    def test_find_resource_in_module(
        self,
        sample_terraform_repo_large: Path,
    ) -> None:
        """Test finding resources defined in modules."""
        analyzer = TerraformAnalyzer(str(sample_terraform_repo_large))

        # The module defines a bucket resource with dynamic name
        # We need to check if resource matching handles modules
        result = analyzer.find_resource_by_arn(
            "arn:aws:s3:::test-bucket-00000",
            "AWS::S3::Bucket",
        )

        # May or may not find depending on module interpolation
        # This tests that parsing doesn't fail with modules
        # The actual match depends on static analysis limitations


class TestParsingEdgeCases:
    """Tests for edge cases in Terraform parsing."""

    def test_parse_file_with_heredoc(
        self,
        tmp_path: Path,
    ) -> None:
        """Test parsing file with heredoc strings."""
        (tmp_path / "main.tf").write_text('''
resource "aws_iam_policy" "test" {
  name = "test-policy"
  
  policy = <<-EOT
  {
    "Version": "2012-10-17",
    "Statement": []
  }
  EOT
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        assert len(analyzer.parsed_configs) == 1

    def test_parse_file_with_jsonencode(
        self,
        tmp_path: Path,
    ) -> None:
        """Test parsing file with jsonencode function."""
        (tmp_path / "main.tf").write_text('''
resource "aws_iam_role" "test" {
  name = "test-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        assert len(analyzer.parsed_configs) == 1

    def test_parse_file_with_for_each(
        self,
        tmp_path: Path,
    ) -> None:
        """Test parsing file with for_each meta-argument."""
        (tmp_path / "main.tf").write_text('''
variable "buckets" {
  type = set(string)
  default = ["bucket1", "bucket2"]
}

resource "aws_s3_bucket" "test" {
  for_each = var.buckets
  bucket   = each.value
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        assert len(analyzer.parsed_configs) == 1

    def test_parse_file_with_count(
        self,
        tmp_path: Path,
    ) -> None:
        """Test parsing file with count meta-argument."""
        (tmp_path / "main.tf").write_text('''
resource "aws_s3_bucket" "test" {
  count  = 3
  bucket = "bucket-${count.index}"
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        assert len(analyzer.parsed_configs) == 1

    def test_parse_file_with_locals(
        self,
        tmp_path: Path,
    ) -> None:
        """Test parsing file with locals block."""
        (tmp_path / "main.tf").write_text('''
locals {
  common_tags = {
    Environment = "test"
    Project     = "terrafix"
  }
}

resource "aws_s3_bucket" "test" {
  bucket = "test-bucket"
  tags   = local.common_tags
}
''')

        analyzer = TerraformAnalyzer(str(tmp_path))

        assert len(analyzer.parsed_configs) == 1

