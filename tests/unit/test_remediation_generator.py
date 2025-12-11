"""
Unit tests for TerraformRemediationGenerator.

Tests cover prompt construction, Bedrock API invocation, response parsing,
and error handling with mocked Bedrock client.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError  # pyright: ignore[reportMissingTypeStubs]

from terrafix.errors import BedrockError
from terrafix.remediation_generator import (
    RemediationFix,
    TerraformRemediationGenerator,
)
from terrafix.vanta_client import Failure


class TestRemediationFixModel:
    """Tests for the RemediationFix Pydantic model."""

    def test_remediation_fix_creation(self) -> None:
        """Test creating a RemediationFix with all fields."""
        fix = RemediationFix(
            fixed_config='resource "aws_s3_bucket" "test" { bucket = "test" }',
            explanation="Added public access block",
            changed_attributes=["block_public_acls"],
            reasoning="Compliance requires blocking public access",
            confidence="high",
            breaking_changes="None identified",
            additional_requirements="None",
        )

        assert fix.fixed_config == 'resource "aws_s3_bucket" "test" { bucket = "test" }'
        assert fix.explanation == "Added public access block"
        assert fix.changed_attributes == ["block_public_acls"]
        assert fix.confidence == "high"

    def test_remediation_fix_default_values(self) -> None:
        """Test that optional fields have correct defaults."""
        fix = RemediationFix(
            fixed_config='resource "aws_s3_bucket" "test" {}',
            explanation="Test fix",
            confidence="medium",
        )

        assert fix.changed_attributes == []
        assert fix.reasoning == ""
        assert fix.breaking_changes == "None identified"
        assert fix.additional_requirements == "None"


class TestTerraformRemediationGeneratorInit:
    """Tests for TerraformRemediationGenerator initialization."""

    @patch("boto3.client")
    def test_init_creates_bedrock_client(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test that init creates Bedrock client with correct config."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        generator = TerraformRemediationGenerator(
            model_id="anthropic.claude-opus-4-5-20251101-v1:0",
            region="us-west-2",
            read_timeout_seconds=3600,
        )

        mock_boto_client.assert_called_once()
        call_kwargs = mock_boto_client.call_args.kwargs
        assert call_kwargs["service_name"] == "bedrock-runtime"
        assert call_kwargs["region_name"] == "us-west-2"

        assert generator.model_id == "anthropic.claude-opus-4-5-20251101-v1:0"
        assert generator.system_prompt == generator.DEFAULT_SYSTEM_PROMPT

    @patch("boto3.client")
    def test_init_with_custom_timeout(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test initialization with custom timeout."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        generator = TerraformRemediationGenerator(  # noqa: F841 - assigned for side effect
            read_timeout_seconds=1800,
        )
        _ = generator  # Suppress unused warning

        # The config should be passed to boto3.client
        call_kwargs = mock_boto_client.call_args.kwargs
        assert "config" in call_kwargs


class TestGenerateFix:
    """Tests for TerraformRemediationGenerator.generate_fix method."""

    @patch("boto3.client")
    def test_generate_fix_success(
        self,
        mock_boto_client: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test successful fix generation."""
        # Mock Bedrock response
        mock_response_body = MagicMock()
        mock_response_body.read.return_value = json.dumps({  # pyright: ignore[reportAny]
            "content": [{
                "text": json.dumps({
                    "fixed_config": 'resource "aws_s3_bucket" "test" {}',
                    "explanation": "Added public access block",
                    "changed_attributes": ["block_public_acls"],
                    "reasoning": "Compliance requires blocking",
                    "confidence": "high",
                    "breaking_changes": "None",
                    "additional_requirements": "None",
                })
            }],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }).encode()

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {  # pyright: ignore[reportAny]
            "body": mock_response_body,
            "contentType": "application/json",
        }
        mock_boto_client.return_value = mock_client

        generator = TerraformRemediationGenerator()

        fix = generator.generate_fix(
            failure=sample_failure,
            current_config='resource "aws_s3_bucket" "test" { bucket = "test" }',
            resource_block={"bucket": "test"},
            module_context={},
        )

        assert isinstance(fix, RemediationFix)
        assert fix.confidence == "high"
        mock_client.invoke_model.assert_called_once()  # pyright: ignore[reportAny]

    @patch("boto3.client")
    def test_generate_fix_handles_markdown_wrapped_json(
        self,
        mock_boto_client: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test parsing when Claude wraps JSON in markdown code blocks."""
        # Response with JSON wrapped in ```json ... ```
        json_content = json.dumps({
            "fixed_config": 'resource "test" {}',
            "explanation": "Test",
            "changed_attributes": [],
            "confidence": "medium",
        })

        mock_response_body = MagicMock()
        mock_response_body.read.return_value = json.dumps({  # pyright: ignore[reportAny]
            "content": [{
                "text": f"Here's the fix:\n```json\n{json_content}\n```\n"
            }],
            "stop_reason": "end_turn",
        }).encode()

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {  # pyright: ignore[reportAny]
            "body": mock_response_body,
            "contentType": "application/json",
        }
        mock_boto_client.return_value = mock_client

        generator = TerraformRemediationGenerator()

        fix = generator.generate_fix(
            failure=sample_failure,
            current_config="",
            resource_block={},
            module_context={},
        )

        assert fix.confidence == "medium"

    @patch("boto3.client")
    def test_generate_fix_throttling_is_retryable(
        self,
        mock_boto_client: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that ThrottlingException is marked as retryable."""
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = ClientError(  # pyright: ignore[reportAny]
            {
                "Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"},
                "ResponseMetadata": {"RequestId": "req-123"},
            },
            "InvokeModel",
        )
        mock_boto_client.return_value = mock_client

        generator = TerraformRemediationGenerator()

        with pytest.raises(BedrockError) as exc_info:
            _ = generator.generate_fix(
                failure=sample_failure,
                current_config="",
                resource_block={},
                module_context={},
            )

        assert exc_info.value.retryable is True
        assert exc_info.value.error_code == "ThrottlingException"

    @patch("boto3.client")
    def test_generate_fix_validation_error_not_retryable(
        self,
        mock_boto_client: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that ValidationException is not retryable."""
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = ClientError(  # pyright: ignore[reportAny]
            {
                "Error": {"Code": "ValidationException", "Message": "Invalid input"},
                "ResponseMetadata": {"RequestId": "req-123"},
            },
            "InvokeModel",
        )
        mock_boto_client.return_value = mock_client

        generator = TerraformRemediationGenerator()

        with pytest.raises(BedrockError) as exc_info:
            _ = generator.generate_fix(
                failure=sample_failure,
                current_config="",
                resource_block={},
                module_context={},
            )

        assert exc_info.value.retryable is False


class TestConstructPrompt:
    """Tests for TerraformRemediationGenerator._construct_prompt method."""

    @patch("boto3.client")
    def test_prompt_contains_xml_tags(
        self,
        mock_boto_client: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that prompt uses XML tags for structure."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        prompt = generator._construct_prompt(  # pyright: ignore[reportPrivateUsage]
            failure=sample_failure,
            current_config='resource "aws_s3_bucket" "test" {}',
            resource_block={"bucket": "test"},
            module_context={"provider": []},
        )

        # Check for XML tags per Anthropic best practices
        assert "<compliance_failure>" in prompt
        assert "</compliance_failure>" in prompt
        assert "<test_name>" in prompt
        assert "<severity>" in prompt
        assert "<current_terraform_configuration>" in prompt
        assert "<task>" in prompt
        assert "<output_format>" in prompt
        assert "<critical_constraints>" in prompt

    @patch("boto3.client")
    def test_prompt_contains_failure_details(
        self,
        mock_boto_client: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that prompt includes all failure details."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        prompt = generator._construct_prompt(  # pyright: ignore[reportPrivateUsage]
            failure=sample_failure,
            current_config="",
            resource_block={},
            module_context={},
        )

        assert sample_failure.test_name in prompt
        assert sample_failure.resource_arn in prompt
        assert sample_failure.severity in prompt
        assert sample_failure.framework in prompt
        assert sample_failure.failure_reason in prompt

    @patch("boto3.client")
    def test_prompt_contains_current_config(
        self,
        mock_boto_client: MagicMock,
        sample_failure: Failure,
    ) -> None:
        """Test that prompt includes current Terraform config."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()
        current_config = '''resource "aws_s3_bucket" "my_bucket" {
  bucket = "my-special-bucket"
}'''

        prompt = generator._construct_prompt(  # pyright: ignore[reportPrivateUsage]
            failure=sample_failure,
            current_config=current_config,
            resource_block={},
            module_context={},
        )

        assert "my-special-bucket" in prompt
        assert "aws_s3_bucket" in prompt


class TestGetTerraformDocsForResource:
    """Tests for TerraformRemediationGenerator._get_terraform_docs_for_resource method."""

    @patch("boto3.client")
    def test_get_docs_for_s3_bucket(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test getting docs for S3 bucket resource."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        docs = generator._get_terraform_docs_for_resource("AWS::S3::Bucket")  # pyright: ignore[reportPrivateUsage]

        assert "aws_s3_bucket" in docs
        assert "block_public_acls" in docs
        assert "server_side_encryption" in docs.lower() or "encryption" in docs.lower()

    @patch("boto3.client")
    def test_get_docs_for_iam_role(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test getting docs for IAM role resource."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        docs = generator._get_terraform_docs_for_resource("AWS::IAM::Role")  # pyright: ignore[reportPrivateUsage]

        assert "aws_iam_role" in docs
        assert "assume_role_policy" in docs

    @patch("boto3.client")
    def test_get_docs_for_unknown_resource(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test getting docs for unknown resource type."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        docs = generator._get_terraform_docs_for_resource("AWS::Unknown::Resource")  # pyright: ignore[reportPrivateUsage]

        assert "No specific docs available" in docs


class TestInvokeClaude:
    """Tests for TerraformRemediationGenerator._invoke_claude method."""

    @patch("boto3.client")
    def test_invoke_claude_request_structure(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test that invoke_model is called with correct structure."""
        mock_response_body = MagicMock()
        mock_response_body.read.return_value = json.dumps({  # pyright: ignore[reportAny]
            "content": [{"text": "{}"}],
            "stop_reason": "end_turn",
        }).encode()

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {  # pyright: ignore[reportAny]
            "body": mock_response_body,
            "contentType": "application/json",
        }
        mock_boto_client.return_value = mock_client

        generator = TerraformRemediationGenerator()
        _ = generator._invoke_claude("test prompt")  # pyright: ignore[reportPrivateUsage]

        # Verify the call structure
        call_args = mock_client.invoke_model.call_args  # pyright: ignore[reportAny]
        assert call_args.kwargs["modelId"] == generator.model_id  # pyright: ignore[reportAny]
        assert call_args.kwargs["contentType"] == "application/json"  # pyright: ignore[reportAny]
        assert call_args.kwargs["accept"] == "application/json"  # pyright: ignore[reportAny]

        # Parse the body to verify structure
        body = json.loads(call_args.kwargs["body"])  # pyright: ignore[reportAny]
        assert body["anthropic_version"] == "bedrock-2023-05-31"
        assert body["max_tokens"] == 4096
        assert body["temperature"] == 0.1
        assert "system" in body
        assert "messages" in body
        messages: list[dict[str, str]] = body["messages"]  # pyright: ignore[reportAny]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "test prompt"


class TestParseResponse:
    """Tests for TerraformRemediationGenerator._parse_response method."""

    @patch("boto3.client")
    def test_parse_valid_response(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test parsing valid Claude response."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        response: dict[str, object] = {
            "content": [{
                "text": json.dumps({
                    "fixed_config": "test config",
                    "explanation": "test explanation",
                    "changed_attributes": ["attr1", "attr2"],
                    "reasoning": "test reasoning",
                    "confidence": "high",
                    "breaking_changes": "None",
                    "additional_requirements": "None",
                })
            }],
            "stop_reason": "end_turn",
        }

        fix = generator._parse_response(response)  # pyright: ignore[reportPrivateUsage]

        assert fix.fixed_config == "test config"
        assert fix.explanation == "test explanation"
        assert fix.changed_attributes == ["attr1", "attr2"]
        assert fix.confidence == "high"

    @patch("boto3.client")
    def test_parse_empty_response_raises(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test that empty response raises BedrockError."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        response: dict[str, object] = {"content": []}

        with pytest.raises(BedrockError) as exc_info:
            _ = generator._parse_response(response)  # pyright: ignore[reportPrivateUsage]

        assert "Empty Claude response" in str(exc_info.value)

    @patch("boto3.client")
    def test_parse_invalid_json_raises(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test that invalid JSON raises BedrockError."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        response: dict[str, object] = {
            "content": [{"text": "not valid json {{{"}]
        }

        with pytest.raises(BedrockError) as exc_info:
            _ = generator._parse_response(response)  # pyright: ignore[reportPrivateUsage]

        assert "Invalid JSON" in str(exc_info.value)

    @patch("boto3.client")
    def test_parse_missing_required_field_raises(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test that missing required field raises BedrockError."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        # Missing "confidence" field
        response: dict[str, object] = {
            "content": [{
                "text": json.dumps({
                    "fixed_config": "test",
                    "explanation": "test",
                    # "confidence" is missing
                })
            }]
        }

        with pytest.raises(BedrockError) as exc_info:
            _ = generator._parse_response(response)  # pyright: ignore[reportPrivateUsage]

        assert "Missing required field" in str(exc_info.value)
        assert "confidence" in str(exc_info.value)

    @patch("boto3.client")
    def test_parse_response_strips_markdown(
        self,
        mock_boto_client: MagicMock,
    ) -> None:
        """Test that markdown code blocks are stripped from response."""
        mock_boto_client.return_value = MagicMock()

        generator = TerraformRemediationGenerator()

        json_content = json.dumps({
            "fixed_config": "test",
            "explanation": "test",
            "confidence": "high",
        })

        response: dict[str, object] = {
            "content": [{
                "text": f"```json\n{json_content}\n```"
            }]
        }

        fix = generator._parse_response(response)  # pyright: ignore[reportPrivateUsage]

        assert fix.fixed_config == "test"
        assert fix.confidence == "high"

