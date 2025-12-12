"""
TerraFix: AI-Powered Terraform Compliance Remediation Bot.

TerraFix monitors Vanta compliance failures, analyzes Terraform configurations,
generates compliant fixes using Claude Opus 4.5 via AWS Bedrock, and opens
GitHub Pull Requests for human review. This human-in-the-loop architecture
ensures that compliance fixes are reviewed before being applied to infrastructure.

Key Components:
    - VantaClient: Polls Vanta API for compliance test failures
    - TerraformAnalyzer: Parses and analyzes Terraform configurations
    - TerraformRemediationGenerator: Uses AWS Bedrock Claude to generate fixes
    - GitHubPRCreator: Creates Pull Requests with detailed context
    - StateStore: SQLite-based deduplication of processed failures
    - Orchestrator: Coordinates the end-to-end remediation pipeline
    - Service: Long-running worker that polls and processes failures

Architecture:
    Vanta Platform → TerraFix Worker → AWS Bedrock Claude → GitHub PR
                           ↓
                    SQLite State Store

Environment Variables:
    VANTA_API_TOKEN: OAuth token for Vanta API (required)
    GITHUB_TOKEN: GitHub personal access token with repo scope (required)
    AWS_REGION: AWS region for Bedrock (required)
    AWS_ACCESS_KEY_ID: AWS credentials (required)
    AWS_SECRET_ACCESS_KEY: AWS credentials (required)
    BEDROCK_MODEL_ID: Claude model ID (default: anthropic.claude-opus-4-5-20251101-v1:0)
    POLL_INTERVAL_SECONDS: Polling interval in seconds (default: 300)
    SQLITE_PATH: Path to SQLite database (default: ./terrafix.db)
    GITHUB_REPO_MAPPING: JSON mapping of resource patterns to repos (optional)
    TERRAFORM_PATH: Path within repos to Terraform files (default: .)
    MAX_CONCURRENT_WORKERS: Max parallel failure processing (default: 3)

Usage:
    # Run as long-running worker
    python -m terrafix.service

    # Process a single failure (for testing)
    python -m terrafix.cli process-once --failure-json failure.json

Author: TerraFix Team
Version: 0.1.0
License: MIT
"""

__version__ = "0.1.0"
__author__ = "TerraFix Team"

__all__ = [
    "__version__",
    "__author__",
]
