# TerraFix Deployment Guide

This guide provides step-by-step instructions for deploying TerraFix in production.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development Setup](#local-development-setup)
3. [Docker Deployment](#docker-deployment)
4. [ECS/Fargate Production Deployment](#ecsfargate-production-deployment)
5. [Configuration](#configuration)
6. [Monitoring and Operations](#monitoring-and-operations)
7. [Troubleshooting](#troubleshooting)

## Prerequisites

### Required

- **Python 3.14**: TerraFix requires Python 3.14 (released November 2025)
- **AWS Account**: With Bedrock access in us-west-2
- **Vanta Account**: OAuth token with `vanta-api.all:read` scope
- **GitHub Account**: Personal access token with `repo` scope
- **Redis**: Production-ready Redis endpoint (Terraform deploys ElastiCache)
- **Git**: For repository cloning operations
- **Terraform CLI**: For infrastructure provisioning (optional for local dev)

### Optional

- **Docker**: For containerized deployment
- **AWS CLI**: For ECS/ECR operations

## Local Development Setup

### 1. Clone Repository

```bash
git clone https://github.com/your-org/terrafix.git
cd terrafix
```

### 2. Create Virtual Environment

```bash
python3.14 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt

# For development
pip install -r requirements-dev.txt
```

### 4. Configure Environment

Create `.env` file:

```bash
# Required
VANTA_API_TOKEN=vanta_oauth_token_here   # scope: vanta-api.all:read
GITHUB_TOKEN=ghp_github_token_here
AWS_REGION=us-west-2
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
REDIS_URL=redis://localhost:6379/0   # For local/dev; Terraform provides in ECS

# Optional
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5-v2:0
POLL_INTERVAL_SECONDS=300
GITHUB_REPO_MAPPING={"default": "your-org/terraform-repo"}
TERRAFORM_PATH=terraform
MAX_CONCURRENT_WORKERS=3
LOG_LEVEL=INFO
STATE_RETENTION_DAYS=7
```

### 5. Run Locally

```bash
# Run service
python -m terrafix.service

# Or process single failure for testing
python -m terrafix.cli process-once --failure-json test_failure.json
```

## Docker Deployment

### 1. Build Image

```bash
docker build -t terrafix:latest .
```

### 2. Run Container

```bash
docker run --env-file .env terrafix:latest
```

### 3. Test Locally

```bash
# Create test failure JSON
cat > test_failure.json << EOF
{
  "test_id": "test-123",
  "test_name": "S3 Bucket Block Public Access",
  "resource_arn": "arn:aws:s3:::my-test-bucket",
  "resource_type": "AWS::S3::Bucket",
  "failure_reason": "Bucket allows public access",
  "severity": "high",
  "framework": "SOC2",
  "failed_at": "2025-11-14T10:00:00Z",
  "current_state": {"block_public_access": false},
  "required_state": {"block_public_access": true}
}
EOF

# Process test failure
docker run --env-file .env -v $(pwd):/data terrafix:latest \
  python -m terrafix.cli process-once --failure-json /data/test_failure.json
```

## ECS/Fargate Production Deployment

### 1. Prerequisites

- Existing VPC with public or private subnets
- AWS credentials configured (`aws configure`)
- Terraform installed

### 2. Create ECR Repository

```bash
cd terraform
terraform init
terraform apply -target=aws_ecr_repository.terrafix
```

### 3. Build and Push Image

```bash
# Get ECR login
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin \
  $(terraform output -raw ecr_repository_url | cut -d'/' -f1)

# Build and tag
docker build -t terrafix:latest .
docker tag terrafix:latest $(terraform output -raw ecr_repository_url):latest

# Push
docker push $(terraform output -raw ecr_repository_url):latest
```

### 4. Configure Terraform Variables

Create `terraform/terraform.tfvars`:

```hcl
# AWS Configuration
aws_region = "us-west-2"
environment = "prod"

# Credentials (sensitive - use secure method to provide these)
vanta_api_token = "vanta_oauth_token"
github_token   = "ghp_github_token"

# Networking (replace with your VPC details)
vpc_id     = "vpc-xxxxx"
subnet_ids = ["subnet-xxxxx", "subnet-yyyyy"]

# Application Configuration
github_repo_mapping = jsonencode({
  default = "your-org/terraform-repo"
})
terraform_path         = "terraform"
poll_interval_seconds  = 300
state_retention_days   = 7

# Redis / ElastiCache
redis_node_type                = "cache.t3.micro"
redis_snapshot_retention_days  = 1

# Resource Sizing
cpu    = 2048    # 2 vCPU
memory = 4096    # 4 GB

# Monitoring
log_retention_days = 30
```

**Security Note**: Do NOT commit `terraform.tfvars` with credentials. Use AWS Secrets Manager, environment variables, or a secure vault.

### 5. Deploy Infrastructure

```bash
cd terraform

# Plan (review changes)
terraform plan

# Apply
terraform apply
```

### 6. Verify Deployment

```bash
# Check service status
aws ecs describe-services \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --services $(terraform output -raw ecs_service_name) \
  --query 'services[0].{Status:status,DesiredCount:desiredCount,RunningCount:runningCount}'

# Tail logs
aws logs tail $(terraform output -raw cloudwatch_log_group) --follow
```

## Configuration

### Environment Variables

All configuration is via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VANTA_API_TOKEN` | Yes | - | Vanta OAuth token (`vanta-api.all:read`) |
| `GITHUB_TOKEN` | Yes | - | GitHub PAT with repo scope |
| `AWS_REGION` | Yes | - | AWS region for Bedrock |
| `AWS_ACCESS_KEY_ID` | Yes | - | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | Yes | - | AWS credentials |
| `BEDROCK_MODEL_ID` | No | `anthropic.claude-sonnet-4-5-v2:0` | Claude model ID |
| `POLL_INTERVAL_SECONDS` | No | `300` | Vanta polling interval |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection URL (Terraform sets in ECS) |
| `GITHUB_REPO_MAPPING` | No | `{"default": ""}` | Resource to repo mapping |
| `TERRAFORM_PATH` | No | `.` | Path to .tf files in repos |
| `MAX_CONCURRENT_WORKERS` | No | `3` | Max parallel processing |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `STATE_RETENTION_DAYS` | No | `7` | Days to keep state records |

### GitHub Repository Mapping

The `GITHUB_REPO_MAPPING` environment variable maps AWS resources to GitHub repositories:

```json
{
  "default": "myorg/terraform-main",
  "arn:aws:s3:::special-bucket": "myorg/terraform-s3",
  "arn:aws:iam::123456:role": "myorg/terraform-iam"
}
```

- `default`: Fallback repository for unmapped resources
- Exact ARN matches take priority
- Prefix matches work for patterns

## Monitoring and Operations

### CloudWatch Logs

View structured JSON logs:

```bash
# Tail logs
aws logs tail /ecs/terrafix-prod --follow

# Query errors
aws logs start-query \
  --log-group-name /ecs/terrafix-prod \
  --start-time $(date -u -d '1 hour ago' +%s) \
  --end-time $(date -u +%s) \
  --query-string 'fields @timestamp, message | filter level = "ERROR" | sort @timestamp desc'
```

### State Store Statistics

```bash
# Via CLI
python -m terrafix.cli stats

# Output:
# State Store Statistics:
#   Total records: 42
#   Pending: 0
#   In Progress: 2
#   Completed: 38
#   Failed: 2
```

### Update Deployment

```bash
# Build and push new image
docker build -t terrafix:latest .
docker tag terrafix:latest $(terraform output -raw ecr_repository_url):latest
docker push $(terraform output -raw ecr_repository_url):latest

# Force new deployment
aws ecs update-service \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --service $(terraform output -raw ecs_service_name) \
  --force-new-deployment
```

### Cleanup Old State Records

```bash
# Via CLI
python -m terrafix.cli cleanup --retention-days 7

# Automatic cleanup runs every 10 polling cycles
```

## Troubleshooting

### Task Not Starting

**Symptoms**: ECS task immediately stops or fails to start

**Diagnosis**:
```bash
# Check task status
aws ecs describe-tasks \
  --cluster terrafix-prod \
  --tasks $(aws ecs list-tasks --cluster terrafix-prod --query 'taskArns[0]' --output text)

# View logs
aws logs tail /ecs/terrafix-prod --since 10m
```

**Common Causes**:
- Missing or invalid Secrets Manager secrets
- IAM role permissions insufficient
- Invalid configuration (check `ConfigurationError` in logs)
- Bedrock model not available in region

### No Failures Being Processed

**Symptoms**: Service running but no PRs created

**Diagnosis**:
```bash
# Check logs for Vanta API calls
aws logs tail /ecs/terrafix-prod --follow | grep "Fetched failing tests"

# Output should show:
# {"level": "INFO", "message": "Fetched failing tests from Vanta", "count": 5}
```

**Common Causes**:
- Invalid Vanta API token
- No failing tests in Vanta
- `GITHUB_REPO_MAPPING` not configured (resources can't be mapped)
- All failures already processed (check state store)

### Bedrock API Errors

**Symptoms**: Processing fails with `BedrockError`

**Diagnosis**:
```bash
# Check for Bedrock errors
aws logs tail /ecs/terrafix-prod | grep "BedrockError"
```

**Common Causes**:
- Model not available in region (use us-west-2)
- Throttling (retries will handle this)
- Invalid AWS credentials
- Model ID incorrect

### Duplicate PRs Created

**Symptoms**: Multiple PRs for same failure

**Expected Behavior**: With Redis state store, duplicates should be rare. If seen:

**Diagnosis**:
- Check Redis connectivity (ECS task to ElastiCache security group)
- Verify deduplication hash inputs (test_id/resource_arn)

**Solutions**:
- Ensure `REDIS_URL` is set correctly in task definition
- Confirm ElastiCache is reachable from ECS task subnets/security groups

### GitHub Rate Limiting

**Symptoms**: PRs fail with 429 status code

**Diagnosis**:
```bash
aws logs tail /ecs/terrafix-prod | grep "rate_limit"
```

**Solution**: Service automatically retries with backoff. For high-volume scenarios, consider GitHub App authentication (higher limits).

### High Memory Usage

**Symptoms**: Task OOM killed

**Diagnosis**:
```bash
# Check Container Insights metrics
aws cloudwatch get-metric-statistics \
  --namespace ECS/ContainerInsights \
  --metric-name MemoryUtilized \
  --dimensions Name=ClusterName,Value=terrafix-prod \
  --start-time $(date -u -d '1 hour ago' --iso-8601=seconds) \
  --end-time $(date -u --iso-8601=seconds) \
  --period 300 \
  --statistics Average
```

**Solution**: Increase memory in `terraform/variables.tf`:
```hcl
memory = 8192 # 8 GB
```

## Security Best Practices

1. **Secrets Management**: Store credentials in AWS Secrets Manager, not environment variables
2. **IAM Roles**: Use least-privilege roles (provided by Terraform)
3. **Network Security**: Use private subnets with NAT gateway
4. **Image Scanning**: Enable ECR vulnerability scanning (configured)
5. **Log Encryption**: CloudWatch Logs encrypted at rest by default
6. **Non-Root User**: Container runs as non-root user
7. **Token Rotation**: Rotate Vanta and GitHub tokens regularly

## Support

For issues or questions:
- Check logs first: `aws logs tail /ecs/terrafix-prod --follow`
- Review this guide and `terraform/README.md`
- Check GitHub issues for known problems
- File new issue with logs and configuration (redact secrets)

