"""
Bedrock Claude integration for compliance diagnosis.

This module provides an interface to Amazon Bedrock's Claude Sonnet 4.5 model
for analyzing compliance failures and generating remediation plans. It constructs
structured prompts, invokes the model, and parses JSON responses.

Classes:
    ClaudeRemediationAgent: Main class for interacting with Claude via Bedrock
"""

import json
import logging
from typing import Dict, Any
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ClaudeRemediationAgent:
    """
    Uses Claude Sonnet 4.5 via Bedrock to analyze compliance failures.
    
    This class encapsulates all interactions with Amazon Bedrock's Claude model,
    including prompt construction, model invocation, and response parsing. It
    generates structured remediation plans based on compliance failure events.
    
    Attributes:
        bedrock_client: Boto3 Bedrock Runtime client for API calls
        model_id: Claude model identifier (e.g., anthropic.claude-sonnet-4-5-v2:0)
        max_tokens: Maximum response tokens to request from Claude
    """
    
    def __init__(
        self,
        model_id: str = "anthropic.claude-sonnet-4-5-v2:0",
        max_tokens: int = 2000,
        region: str = "us-east-1"
    ):
        """
        Initialize Claude agent with Bedrock client.
        
        Args:
            model_id: Bedrock model ID for Claude (default: claude-sonnet-4-5-v2:0)
            max_tokens: Maximum response length in tokens (default: 2000)
            region: AWS region for Bedrock service (default: us-east-1)
        """
        self.bedrock_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=region
        )
        self.model_id = model_id
        self.max_tokens = max_tokens
    
    def diagnose_and_remediate(
        self,
        vanta_event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze compliance failure and generate remediation command.
        
        This is the main entry point for generating remediation plans. It takes
        a compliance failure event, constructs a prompt, invokes Claude, and
        returns a structured remediation plan.
        
        Args:
            vanta_event: Compliance failure event containing:
                - test_name: Name of the failed test
                - resource_arn: ARN of the affected resource
                - resource_type: AWS resource type
                - failure_reason: Description of the failure
                - current_state: Current resource configuration
                - required_state: Required resource configuration
            
        Returns:
            Dictionary containing:
                - diagnosis: Root cause analysis of the failure
                - resource_arn: Full ARN of the affected resource
                - resource_type: AWS service type (S3, IAM, EC2, etc.)
                - remediation_command: Natural language instruction for fixing the issue
                - reasoning: Step-by-step logic explaining the remediation
                - confidence: Confidence level (high, medium, or low)
                - estimated_impact: Description of what will change
            
        Raises:
            ClientError: If Bedrock API fails (auth, throttling, model access issues)
            ValueError: If Claude response is invalid or missing required fields
        """
        prompt = self._construct_prompt(vanta_event)
        
        try:
            response = self._invoke_claude(prompt)
            return self._parse_response(response)
        except ClientError as e:
            logger.error(f"Bedrock error: {e}")
            raise
    
    def _construct_prompt(self, vanta_event: Dict[str, Any]) -> str:
        """
        Build structured prompt for Claude with compliance failure details.
        
        This method creates a detailed prompt that instructs Claude to act as
        a cloud security architect and generate a precise remediation plan.
        
        Args:
            vanta_event: Compliance failure event data
            
        Returns:
            Formatted prompt string with instructions and event details
        """
        return f"""You are a principal cloud security architect specializing in AWS compliance remediation.

COMPLIANCE FAILURE:
{json.dumps(vanta_event, indent=2)}

TASK:
1. Identify root cause of failure
2. Determine affected AWS resource
3. Generate precise, unambiguous remediation command

RESPONSE FORMAT (JSON):
{{
  "diagnosis": "Root cause analysis",
  "resource_arn": "Full ARN of resource",
  "resource_type": "AWS service (S3, IAM, EC2)",
  "remediation_command": "Natural language instruction. Example: 'Enable S3 Block Public Access for bucket example-bucket with all four settings'",
  "reasoning": "Step-by-step logic",
  "confidence": "high|medium|low",
  "estimated_impact": "What will change"
}}

REQUIREMENTS:
- Command must be actionable and specific
- Include exact resource identifiers
- Consider blast radius - prefer least-privilege
- Address the compliance control requirement

Generate JSON response now:"""
    
    def _invoke_claude(self, prompt: str) -> Dict[str, Any]:
        """
        Call Bedrock to invoke Claude model.
        
        This method handles the low-level API call to Amazon Bedrock, including
        request formatting and response handling.
        
        Args:
            prompt: Constructed prompt string for Claude
            
        Returns:
            Raw Bedrock response dictionary containing Claude's response
            
        Raises:
            ClientError: If API call fails due to:
                - Authentication issues
                - Missing model access permissions
                - Throttling limits
                - Service errors
        """
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "top_p": 0.9
        }
        
        logger.info(f"Invoking {self.model_id}")
        
        response = self.bedrock_client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )
        
        return json.loads(response["body"].read())
    
    def _parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract structured data from Claude response.
        
        This method parses Claude's response, handling both plain JSON and
        markdown-wrapped JSON responses. It validates that all required fields
        are present in the response.
        
        Args:
            response: Raw Bedrock response containing Claude's output
            
        Returns:
            Parsed remediation plan dictionary with validated fields
            
        Raises:
            ValueError: If:
                - Response is empty
                - JSON parsing fails
                - Required fields are missing
        """
        content = response.get("content", [])
        if not content:
            raise ValueError("Empty Claude response")
        
        text = content[0].get("text", "")
        
        # Claude may wrap JSON in markdown code blocks
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0].strip()
        else:
            json_str = text.strip()
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\nText: {text}")
            raise ValueError(f"Invalid JSON: {e}")
        
        # Validate required fields
        required = ["diagnosis", "remediation_command", "confidence"]
        for field in required:
            if field not in data:
                raise ValueError(f"Missing field: {field}")
        
        return data
