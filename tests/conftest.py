"""
Shared pytest fixtures for TerraFix tests.

This module provides common test fixtures used across unit and integration tests.
Fixtures include mocked clients, sample data objects, and temporary file structures.

Usage:
    def test_something(mock_settings, sample_failure):
        # Fixtures are injected automatically by pytest
        assert sample_failure.test_id == "test-s3-001"
"""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses
from _pytest.monkeypatch import MonkeyPatch

# Import TerraFix types
from terrafix.config import Settings
from terrafix.remediation_generator import RemediationFix
from terrafix.vanta_client import Failure


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def mock_env_vars(monkeypatch: MonkeyPatch) -> dict[str, str]:
    """
    Set up mock environment variables for testing.

    Provides all required environment variables with fake values
    so Settings can be instantiated without real credentials.

    Args:
        monkeypatch: pytest monkeypatch fixture

    Returns:
        Dictionary of environment variable names and values
    """
    env_vars = {
        "VANTA_API_TOKEN": "test_vanta_token_12345",
        "GITHUB_TOKEN": "ghp_test_github_token_67890",
        "AWS_REGION": "us-west-2",
        "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "BEDROCK_MODEL_ID": "anthropic.claude-opus-4-5-20251101-v1:0",
        "POLL_INTERVAL_SECONDS": "60",
        "REDIS_URL": "redis://localhost:6379/0",
        "GITHUB_REPO_MAPPING": '{"default": "test-org/terraform-repo"}',
        "TERRAFORM_PATH": "terraform",
        "MAX_CONCURRENT_WORKERS": "2",
        "LOG_LEVEL": "DEBUG",
        "STATE_RETENTION_DAYS": "7",
    }

    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)

    return env_vars


@pytest.fixture
def mock_settings(mock_env_vars: dict[str, str]) -> Settings:
    """
    Provide test Settings instance with fake credentials.

    Uses mock_env_vars fixture to set up environment, then
    creates a Settings instance. The lru_cache on get_settings
    is bypassed by creating Settings directly.

    Args:
        mock_env_vars: Environment variables fixture (used for side effects)

    Returns:
        Configured Settings instance for testing
    """
    # Suppress unused variable warning - fixture is used for side effects
    _ = mock_env_vars
    # Create Settings directly to bypass lru_cache
    # Settings reads from environment variables set by mock_env_vars
    return Settings()  # pyright: ignore[reportCallIssue]


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_failure() -> Failure:
    """
    Provide a sample Vanta Failure object for testing.

    Creates a realistic S3 bucket compliance failure that can be
    used to test the full remediation pipeline.

    Returns:
        Sample Failure object representing S3 public access violation
    """
    return Failure(
        test_id="test-s3-001",
        test_name="S3 Bucket Block Public Access",
        resource_arn="arn:aws:s3:::test-bucket-12345",
        resource_type="AWS::S3::Bucket",
        failure_reason="S3 bucket does not have public access blocked",
        severity="high",
        framework="SOC2",
        failed_at="2025-01-15T10:30:00Z",
        current_state={
            "block_public_acls": False,
            "block_public_policy": False,
            "ignore_public_acls": False,
            "restrict_public_buckets": False,
        },
        required_state={
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True,
        },
        resource_id="res-s3-12345",
        resource_details={"bucket_name": "test-bucket-12345"},
    )


@pytest.fixture
def sample_failure_iam() -> Failure:
    """
    Provide a sample IAM role compliance failure for testing.

    Returns:
        Sample Failure object representing IAM role violation
    """
    return Failure(
        test_id="test-iam-001",
        test_name="IAM Role Maximum Session Duration",
        resource_arn="arn:aws:iam::123456789012:role/test-role",
        resource_type="AWS::IAM::Role",
        failure_reason="IAM role does not have maximum session duration configured",
        severity="medium",
        framework="SOC2",
        failed_at="2025-01-15T11:00:00Z",
        current_state={
            "max_session_duration": 43200,
        },
        required_state={
            "max_session_duration": 3600,
        },
        resource_id="res-iam-67890",
        resource_details={"role_name": "test-role"},
    )


@pytest.fixture
def sample_remediation_fix() -> RemediationFix:
    """
    Provide a sample RemediationFix object for testing.

    Returns:
        Sample RemediationFix with S3 bucket public access block fix
    """
    return RemediationFix(
        fixed_config='''resource "aws_s3_bucket" "test_bucket" {
  bucket = "test-bucket-12345"
  
  tags = {
    Environment = "test"
  }
}

resource "aws_s3_bucket_public_access_block" "test_bucket" {
  bucket = aws_s3_bucket.test_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
''',
        explanation="Added aws_s3_bucket_public_access_block resource to block all public access to the S3 bucket.",
        changed_attributes=[
            "block_public_acls",
            "block_public_policy",
            "ignore_public_acls",
            "restrict_public_buckets",
        ],
        reasoning="The compliance failure requires blocking all forms of public access. Adding a public access block resource is the recommended approach.",
        confidence="high",
        breaking_changes="None identified",
        additional_requirements="None",
    )


# =============================================================================
# Terraform Repository Fixtures
# =============================================================================


@pytest.fixture
def sample_terraform_repo(tmp_path: Path) -> Path:
    """
    Create a temporary Terraform repository with sample .tf files.

    Creates a directory structure with realistic Terraform files
    that can be used to test the TerraformAnalyzer.

    Args:
        tmp_path: pytest temporary directory fixture

    Returns:
        Path to the temporary Terraform repository
    """
    # Create main.tf
    main_tf = tmp_path / "main.tf"
    _ = main_tf.write_text('''terraform {
  required_version = ">= 1.0.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
''')

    # Create variables.tf
    variables_tf = tmp_path / "variables.tf"
    _ = variables_tf.write_text('''variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "test"
}
''')

    # Create s3.tf with the test bucket
    s3_tf = tmp_path / "s3.tf"
    _ = s3_tf.write_text('''resource "aws_s3_bucket" "test_bucket" {
  bucket = "test-bucket-12345"
  
  tags = {
    Environment = var.environment
    Name        = "test-bucket-12345"
  }
}

resource "aws_s3_bucket_versioning" "test_bucket" {
  bucket = aws_s3_bucket.test_bucket.id
  
  versioning_configuration {
    status = "Enabled"
  }
}
''')

    # Create iam.tf
    iam_tf = tmp_path / "iam.tf"
    _ = iam_tf.write_text('''resource "aws_iam_role" "test_role" {
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
  
  tags = {
    Environment = var.environment
  }
}
''')

    # Create outputs.tf
    outputs_tf = tmp_path / "outputs.tf"
    _ = outputs_tf.write_text('''output "bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.test_bucket.arn
}

output "role_arn" {
  description = "ARN of the IAM role"
  value       = aws_iam_role.test_role.arn
}
''')

    return tmp_path


@pytest.fixture
def sample_terraform_repo_large(tmp_path: Path) -> Path:
    """
    Create a larger Terraform repository for scalability testing.

    Creates a repository with multiple modules and many resources
    to test parsing performance.

    Args:
        tmp_path: pytest temporary directory fixture

    Returns:
        Path to the temporary Terraform repository
    """
    # Create modules directory structure
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()

    # Create S3 module
    s3_module = modules_dir / "s3"
    s3_module.mkdir()
    _ = (s3_module / "main.tf").write_text('''variable "bucket_name" {
  type = string
}

variable "environment" {
  type = string
}

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name
  
  tags = {
    Environment = var.environment
  }
}

output "bucket_arn" {
  value = aws_s3_bucket.this.arn
}
''')

    # Create main configuration with multiple module calls
    main_tf_content = '''terraform {
  required_version = ">= 1.0.0"
}

'''
    # Add multiple S3 bucket modules to simulate scale
    for i in range(50):
        main_tf_content += f'''
module "bucket_{i}" {{
  source      = "./modules/s3"
  bucket_name = "test-bucket-{i:05d}"
  environment = "test"
}}
'''

    _ = (tmp_path / "main.tf").write_text(main_tf_content)

    return tmp_path


# =============================================================================
# Mock Client Fixtures
# =============================================================================


@pytest.fixture
def mock_vanta_session() -> Generator[responses.RequestsMock, None, None]:
    """
    Provide a mocked requests session for Vanta API calls.

    Uses the responses library to mock HTTP requests to the Vanta API.

    Yields:
        Configured responses mock context
    """
    with responses.RequestsMock() as rsps:
        # Add default OAuth token response
        _ = rsps.add(
            responses.POST,
            "https://api.vanta.com/oauth/token",
            json={
                "access_token": "test_access_token",
                "token_type": "bearer",
                "expires_in": 3600,
            },
            status=200,
        )
        yield rsps


@pytest.fixture
def mock_bedrock_client() -> MagicMock:
    """
    Provide a mocked boto3 Bedrock Runtime client.

    Creates a MagicMock that simulates Bedrock API responses
    for testing the RemediationGenerator without actual API calls.

    Returns:
        Mocked Bedrock client
    """
    mock_client = MagicMock()

    # Create mock response body
    mock_response_body = MagicMock()
    mock_response_body.read.return_value = json.dumps({  # pyright: ignore[reportAny]
        "content": [{
            "text": json.dumps({
                "fixed_config": 'resource "aws_s3_bucket" "test" {}',
                "explanation": "Test fix explanation",
                "changed_attributes": ["test_attr"],
                "reasoning": "Test reasoning",
                "confidence": "high",
                "breaking_changes": "None",
                "additional_requirements": "None",
            })
        }],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }).encode()

    mock_client.invoke_model.return_value = {  # pyright: ignore[reportAny]
        "body": mock_response_body,
        "contentType": "application/json",
    }

    return mock_client


@pytest.fixture
def mock_github_client() -> MagicMock:
    """
    Provide a mocked PyGithub client.

    Creates a MagicMock that simulates GitHub API operations
    for testing the GitHubPRCreator without actual API calls.

    Returns:
        Mocked GitHub client
    """
    mock_client = MagicMock()

    # Mock repository
    mock_repo = MagicMock()
    mock_repo.full_name = "test-org/terraform-repo"
    mock_repo.default_branch = "main"

    # Mock get_git_ref for base branch
    mock_base_ref = MagicMock()
    mock_base_ref.object.sha = "abc123def456"  # pyright: ignore[reportAny]
    mock_repo.get_git_ref.return_value = mock_base_ref  # pyright: ignore[reportAny]

    # Mock create_git_ref for branch creation
    mock_repo.create_git_ref.return_value = MagicMock()  # pyright: ignore[reportAny]

    # Mock get_contents for file content
    mock_file_content = MagicMock()
    mock_file_content.sha = "file_sha_123"
    mock_file_content.decoded_content = b"old content"
    mock_repo.get_contents.return_value = mock_file_content  # pyright: ignore[reportAny]

    # Mock update_file
    mock_repo.update_file.return_value = {"commit": MagicMock()}  # pyright: ignore[reportAny]

    # Mock create_pull
    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/test-org/terraform-repo/pull/1"
    mock_pr.number = 1
    mock_repo.create_pull.return_value = mock_pr  # pyright: ignore[reportAny]

    # Mock get_label (raise for missing labels)
    mock_repo.get_label.side_effect = Exception("Label not found")  # pyright: ignore[reportAny]
    mock_repo.create_label.return_value = MagicMock()  # pyright: ignore[reportAny]

    mock_client.get_repo.return_value = mock_repo  # pyright: ignore[reportAny]

    return mock_client


@pytest.fixture
def mock_redis_client() -> Generator[object, None, None]:
    """
    Provide a mocked Redis client using fakeredis.

    Creates an in-memory Redis mock that can be used to test
    the RedisStateStore without a real Redis server.

    Yields:
        Mocked Redis client via fakeredis (FakeRedis or MagicMock)
    """
    try:
        import fakeredis
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        with patch("redis.from_url", return_value=fake_redis):
            yield fake_redis
    except ImportError:
        # Fallback to MagicMock if fakeredis not available
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True  # pyright: ignore[reportAny]
        mock_redis.set.return_value = True  # pyright: ignore[reportAny]
        mock_redis.get.return_value = None  # pyright: ignore[reportAny]
        mock_redis.scan.return_value = (0, [])  # pyright: ignore[reportAny]
        with patch("redis.from_url", return_value=mock_redis):
            yield mock_redis


# =============================================================================
# VCR.py Configuration
# =============================================================================


@pytest.fixture
def vcr_config() -> dict[str, object]:
    """
    Provide VCR.py configuration for recording/replaying HTTP interactions.

    Returns:
        VCR configuration dictionary
    """
    return {
        "cassette_library_dir": "tests/fixtures/cassettes",
        "record_mode": "none",  # Don't record in CI, only replay
        "match_on": ["uri", "method"],
        "filter_headers": [
            "authorization",
            "x-api-key",
        ],
        "filter_query_parameters": [
            "api_key",
            "token",
        ],
        "decode_compressed_response": True,
    }


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def sample_vanta_api_response() -> dict[str, object]:
    """
    Provide a sample Vanta API response for testing.

    Returns:
        Dictionary matching Vanta API response format
    """
    return {
        "results": {
            "data": [
                {
                    "test_id": "test-s3-001",
                    "test_name": "S3 Bucket Block Public Access",
                    "resource_arn": "arn:aws:s3:::test-bucket-12345",
                    "resource_type": "AWS::S3::Bucket",
                    "failure_reason": "S3 bucket does not have public access blocked",
                    "severity": "high",
                    "framework": "SOC2",
                    "failed_at": "2025-01-15T10:30:00Z",
                    "current_state": {"block_public_acls": False},
                    "required_state": {"block_public_acls": True},
                    "resource_id": "res-s3-12345",
                }
            ],
            "pageInfo": {
                "hasNextPage": False,
                "endCursor": None,
            },
        }
    }


@pytest.fixture(autouse=True)
def reset_singletons() -> Generator[None, None, None]:
    """
    Reset any singleton/cached state between tests.

    This ensures tests don't leak state to each other.

    Yields:
        None (used for cleanup after test)
    """
    # Clear the Settings lru_cache before each test
    from terrafix.config import get_settings
    get_settings.cache_clear()

    yield

    # Clear again after test
    get_settings.cache_clear()

