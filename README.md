# TerraFix: AI-Powered Terraform Compliance Remediation Bot

**TerraFix** is a long-running service that automatically detects Vanta compliance failures, analyzes Terraform configurations, generates compliant fixes using Claude Sonnet 4.5 via AWS Bedrock, and opens GitHub Pull Requests for human review.

## Architecture

```
Vanta Platform → TerraFix Worker → AWS Bedrock Claude → GitHub PR
                       ↓
                 Redis State Store
                       ↓
               Health Check (HTTP)
```

**Key Differentiator**: Human-in-the-loop architecture. No direct AWS access required. We work at the Infrastructure-as-Code layer where changes belong, not directly on cloud resources.

## Components

1. **VantaClient**: Polls Vanta API every 5 minutes for compliance test failures (OAuth with `vanta-api.all:read`)
2. **RateLimiter**: Token-bucket limiting for Vanta API (50/20 rpm)
3. **TerraformAnalyzer**: Parses Terraform HCL and locates failing resources by ARN (rich AWS→TF mapping)
4. **TerraformRemediationGenerator**: Uses AWS Bedrock Claude to generate fixes
5. **TerraformValidator**: Runs `terraform fmt` and `terraform validate` on generated fixes
6. **GitHubPRCreator**: Creates comprehensive PRs with review checklists (atomic branch creation)
7. **SecureGitClient**: Clones repos via credential helper (no tokens in process args)
8. **RedisStateStore**: Redis-based deduplication with TTL to avoid duplicate PRs
9. **HealthCheckServer**: `/health`, `/ready`, `/status` endpoints for ECS/K8s probes
10. **Orchestrator/Service**: Coordinates and runs the end-to-end remediation pipeline

## Prerequisites

- **Python 3.14** (yes, it exists as of November 2025)
- **AWS Account** with Bedrock access in us-west-2
- **Vanta Account** with API access (OAuth token with `vanta-api.all:read`)
- **GitHub Account** with Personal Access Token (repo scope)
- **Redis** endpoint (ElastiCache recommended for production)

## Configuration

All configuration is via environment variables:

### Required

```bash
export VANTA_API_TOKEN="vanta_oauth_token"  # scope: vanta-api.all:read
export GITHUB_TOKEN="github_personal_access_token"
export AWS_REGION="us-west-2"
export AWS_ACCESS_KEY_ID="aws_access_key"
export AWS_SECRET_ACCESS_KEY="aws_secret_key"
export REDIS_URL="redis://localhost:6379/0"
```

### Optional

```bash
export BEDROCK_MODEL_ID="anthropic.claude-sonnet-4-5-v2:0"
export POLL_INTERVAL_SECONDS="300"
export GITHUB_REPO_MAPPING='{"default": "org/terraform-repo"}'
export TERRAFORM_PATH="terraform"
export MAX_CONCURRENT_WORKERS="3"
export LOG_LEVEL="INFO"
export STATE_RETENTION_DAYS="7"
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
- ElastiCache Redis for persistent deduplication state
- Task definition with environment variables from Secrets Manager
- IAM roles with least-privilege access to Bedrock and CloudWatch Logs
- CloudWatch log group for structured JSON logs
- Container health checks on `/health` (port 8080)

## How It Works

1. **Polling**: Worker polls Vanta API every 5 minutes for failing compliance tests (rate-limited)
2. **Deduplication**: Atomically claims failures in Redis to avoid duplicate PRs across restarts/workers
3. **Repository Clone**: Securely clones the target GitHub repository (no token leakage)
4. **Terraform Analysis**: Parses `.tf` files, locates the failing resource by ARN with rich AWS→TF mapping
5. **Fix Generation**: Sends failure context and current Terraform config to Claude via Bedrock
6. **Validation**: Runs `terraform fmt` and `terraform validate` on generated fixes; surfaces warnings
7. **PR Creation**: Opens GitHub PR with comprehensive context, review checklist, and confidence level; atomic branch creation
8. **State Tracking**: Records success/failure in Redis with TTL-based retention

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

- **Terraform-Only**: Currently only supports Terraform (CloudFormation/Pulumi support planned)
- **Polling-Based**: 5-minute polling interval (Vanta webhooks not available)
- **No Automated Testing**: Generated fixes require human review before merging
- **Terraform Binary Required for Validation**: If terraform is unavailable, validation falls back to skip with warnings

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

- **Multi-IaC**: CloudFormation, Pulumi, CDK support
- **Deeper Validation**: Run `terraform plan` in isolated environment
- **Cost Analysis**: Integrate Infracost for cost impact estimates
- **Learning from Feedback**: Track accepted/rejected PRs for continuous improvement
- **Multi-Repository**: Concurrent processing across multiple repos
- **Automated Tests**: Generate Terratest tests for fixes

## Security

- All credentials stored in AWS Secrets Manager (ECS deployment)
- Least-privilege IAM roles for Bedrock, ElastiCache, and CloudWatch access
- No direct AWS resource modifications (only IaC changes via PRs)
- Structured logs with correlation IDs for audit trails
- Read-only Vanta API access (no write permissions needed)
- Secure Git cloning via credential helper (tokens not exposed in process args)

## Support

For issues, questions, or contributions, see the project repository.

## License

MIT License - see LICENSE file for details.

---

**Built with Python 3.14, Claude Sonnet 4.5, and a commitment to keeping humans in the loop.**

