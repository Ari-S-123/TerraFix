"""
Main Lambda handler for self-healing cloud remediation.

This module orchestrates the compliance remediation workflow by:
1. Receiving compliance failure events from EventBridge
2. Diagnosing issues using Claude via Bedrock
3. Executing remediation via AWS SDK
4. Storing results in DynamoDB

Environment Variables:
    BEDROCK_MODEL_ID: Claude model ID (anthropic.claude-sonnet-4-5-v2:0)
    DYNAMODB_TABLE: DynamoDB table name for storing remediation history
    AWS_REGION: AWS region (default: us-east-1)
    LOG_LEVEL: Logging level (default: INFO)
    DRY_RUN: If 'true', simulate remediation without executing (default: true)
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional
import boto3
from claude_client import ClaudeRemediationAgent
from remediation import AWSRemediationExecutor

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
table_name = os.getenv("DYNAMODB_TABLE", "remediation-history")
table = dynamodb.Table(table_name)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Orchestrates compliance remediation workflow.
    
    This function is the main entry point for the Lambda function. It receives
    compliance failure events from EventBridge, uses Claude to diagnose the issue,
    executes the remediation, and stores the results in DynamoDB.
    
    Args:
        event: EventBridge event containing compliance failure details in the 'detail' field
        context: Lambda context object containing request metadata
    
    Input Event Structure (from EventBridge):
    {
      "detail": {
        "test_id": "s3_block_public_access",
        "test_name": "S3 Bucket Block Public Access",
        "severity": "high",
        "resource_type": "AWS::S3::Bucket",
        "resource_arn": "arn:aws:s3:::demo-bucket",
        "failure_reason": "Block Public Access not enabled",
        "current_state": {...},
        "required_state": {...}
      }
    }
    
    Returns:
        Dict containing:
        - statusCode: HTTP status code (200 for success, 500 for error)
        - body: JSON string containing:
          - event_id: Unique event identifier
          - status: 'success' or 'error'
          - diagnosis: Claude's analysis of the issue
          - remediation_command: Natural language remediation instruction
          - action_taken: Description of the action performed
          - dry_run: Whether this was a dry run
    
    Raises:
        ValueError: If the event is missing required fields
        Exception: For any other errors during processing
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    event_id = context.request_id
    timestamp = int(datetime.now().timestamp() * 1000)
    
    try:
        # Extract compliance failure from EventBridge detail
        vanta_event = event.get("detail", {})
        if not vanta_event:
            raise ValueError("Missing detail field in event")
        
        logger.info(f"Processing: {vanta_event.get('test_name', 'unknown')}")
        
        # Step 1: Diagnose with Claude
        logger.info("Step 1: Invoking Bedrock...")
        agent = ClaudeRemediationAgent(
            model_id=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5-v2:0"),
            region=os.getenv("AWS_REGION", "us-east-1")
        )
        remediation_plan = agent.diagnose_and_remediate(vanta_event)
        logger.info(f"Diagnosis: {remediation_plan['diagnosis']}")
        
        # Step 2: Execute remediation
        logger.info("Step 2: Executing remediation...")
        executor = AWSRemediationExecutor(
            dry_run=os.getenv("DRY_RUN", "true").lower() == "true"
        )
        result = executor.execute_remediation(
            remediation_command=remediation_plan["remediation_command"],
            resource_arn=remediation_plan.get("resource_arn", ""),
            resource_type=remediation_plan.get("resource_type", "")
        )
        logger.info(f"Result: {result}")
        
        # Step 3: Store in DynamoDB
        logger.info("Step 3: Storing history...")
        item = {
            "event_id": event_id,
            "timestamp": timestamp,
            "test_name": vanta_event.get("test_name"),
            "resource_arn": remediation_plan.get("resource_arn"),
            "diagnosis": remediation_plan["diagnosis"],
            "remediation_command": remediation_plan["remediation_command"],
            "action_taken": result["action_taken"],
            "status": "success" if result["success"] else "failed",
            "dry_run": result.get("dry_run", True),
            "vanta_event": vanta_event,
            "remediation_plan": remediation_plan
        }
        table.put_item(Item=item)
        
        response = {
            "event_id": event_id,
            "timestamp": timestamp,
            "status": "success",
            "diagnosis": remediation_plan["diagnosis"],
            "remediation_command": remediation_plan["remediation_command"],
            "action_taken": result["action_taken"],
            "dry_run": result.get("dry_run", True)
        }
        
        return {
            "statusCode": 200,
            "body": json.dumps(response)
        }
        
    except Exception as e:
        logger.error(f"Remediation failed: {str(e)}", exc_info=True)
        
        # Store error
        error_item = {
            "event_id": event_id,
            "timestamp": timestamp,
            "status": "error",
            "error": str(e),
            "vanta_event": event.get("detail", {})
        }
        try:
            table.put_item(Item=error_item)
        except Exception as db_error:
            logger.error(f"DynamoDB error: {db_error}")
        
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e), "event_id": event_id})
        }
