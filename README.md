# TerraFix: AI-Powered Terraform Compliance Remediation Bot

**TerraFix** is a long-running service that automatically detects Vanta compliance failures, analyzes Terraform configurations, generates compliant fixes using Claude Sonnet 4.5 via AWS Bedrock, and opens GitHub Pull Requests for human review.

## Architecture

```
Vanta Platform → TerraFix Worker → AWS Bedrock Claude → GitHub PR
                       ↓
                SQLite State Store
```

**Key Differentiator**: Human-in-the-loop architecture. No direct AWS access required. We work at the Infrastructure-as-Code layer where changes belong, not directly on cloud resources.

## Components

1. **VantaClient**: Polls Vanta API every 5 minutes for compliance test failures
2. **TerraformAnalyzer**: Parses Terraform HCL and locates failing resources by ARN
3. **TerraformRemediationGenerator**: Uses AWS Bedrock Claude to generate fixes
4. **GitHubPRCreator**: Creates comprehensive PRs with review checklists
5. **StateStore**: SQLite-based deduplication to avoid duplicate PRs
6. **Orchestrator**: Coordinates the end-to-end remediation pipeline
7. **Service**: Long-running worker loop for continuous monitoring

## Prerequisites

- **Python 3.14** (yes, it exists as of November 2025)
- **AWS Account** with Bedrock access in us-west-2
- **Vanta Account** with API access (OAuth token with `test:read` scope)
- **GitHub Account** with Personal Access Token (repo scope)

## Configuration

All configuration is via environment variables:

### Required

```bash
export VANTA_API_TOKEN="vanta_oauth_token"
export GITHUB_TOKEN="github_personal_access_token"
export AWS_REGION="us-west-2"
export AWS_ACCESS_KEY_ID="aws_access_key"
export AWS_SECRET_ACCESS_KEY="aws_secret_key"
```

### Optional

```bash
export BEDROCK_MODEL_ID="anthropic.claude-sonnet-4-5-v2:0"
export POLL_INTERVAL_SECONDS="300"
export SQLITE_PATH="./terrafix.db"
export GITHUB_REPO_MAPPING='{"default": "org/terraform-repo"}'
export TERRAFORM_PATH="terraform"
export MAX_CONCURRENT_WORKERS="3"
export LOG_LEVEL="INFO"
```

## Installation

```bash
# Create and activate virtual environment (Python 3.14)
python3.14 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# For development
pip install -r requirements-dev.txt
```

## Running Locally

```bash
# Run the long-running worker
python -m terrafix.service

# Process a single failure (for testing)
python -m terrafix.cli process-once --failure-json test_failure.json
```

## Docker Deployment

```bash
# Build image
docker build -t terrafix:latest .

# Run locally
docker run --env-file .env terrafix:latest
```

## ECS/Fargate Deployment

We provide Terraform modules to deploy TerraFix as a single-task Fargate service:

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

This provisions:
- ECR repository for the TerraFix image
- ECS cluster and Fargate service (2 vCPU, 4GB memory)
- Task definition with environment variables from Secrets Manager
- IAM roles with least-privilege access to Bedrock and CloudWatch Logs
- CloudWatch log group for structured JSON logs

**Note**: SQLite state is ephemeral per task. For persistent deduplication across task restarts, mount an EFS volume (future enhancement).

## How It Works

1. **Polling**: Worker polls Vanta API every 5 minutes for failing compliance tests
2. **Deduplication**: Checks SQLite store to avoid reprocessing the same failure
3. **Repository Clone**: Clones the target GitHub repository into a temp directory
4. **Terraform Analysis**: Parses `.tf` files and locates the failing resource by ARN
5. **Fix Generation**: Sends failure context and current Terraform config to Claude via Bedrock
6. **Validation**: Validates generated fix and optionally runs `terraform fmt`
7. **PR Creation**: Opens GitHub PR with comprehensive context, review checklist, and confidence level
8. **State Tracking**: Records success/failure in SQLite for deduplication

## PR Format

Each PR includes:
- Compliance failure details (test name, severity, framework, resource ARN)
- Explanation of changes made by Claude
- Review checklist for human reviewers
- Confidence level (high/medium/low)
- Current vs. required state comparison
- Breaking changes and additional requirements
- Labels for severity and compliance framework

## Limitations

- **SQLite Ephemeral State**: In ECS, SQLite state is lost on task replacement (no EFS mount yet)
- **Single-Task Deployment**: Only one worker task runs at a time to avoid SQLite concurrency issues
- **Terraform-Only**: Currently only supports Terraform (CloudFormation/Pulumi support planned)
- **Polling-Based**: 5-minute polling interval (Vanta webhooks not available as of Nov 2025)
- **No Automated Testing**: Generated fixes require human review before merging

## Development

```bash
# Linting
ruff check src/

# Type checking
mypy src/

# Format
ruff format src/
```

## Future Enhancements

- **Persistent State**: Mount EFS volume for SQLite in ECS
- **Multi-IaC**: CloudFormation, Pulumi, CDK support
- **Terraform Validation**: Run `terraform plan` in isolated environment
- **Cost Analysis**: Integrate Infracost for cost impact estimates
- **Learning from Feedback**: Track accepted/rejected PRs for continuous improvement
- **Multi-Repository**: Concurrent processing across multiple repos
- **Automated Tests**: Generate Terratest tests for fixes

## Security

- All credentials stored in AWS Secrets Manager (ECS deployment)
- Least-privilege IAM roles for Bedrock and CloudWatch access
- No direct AWS resource modifications (only IaC changes via PRs)
- Structured logs with correlation IDs for audit trails
- Read-only Vanta API access (no write permissions needed)

## Support

For issues, questions, or contributions, see the project repository.

## License

MIT License - see LICENSE file for details.

---

**Built with Python 3.14, Claude Sonnet 4.5, and a commitment to keeping humans in the loop.**

