# TerraFix Infrastructure

Terraform configuration for deploying TerraFix as an ECS/Fargate service.

## Prerequisites

- AWS account with Bedrock access in us-west-2
- Existing VPC with public or private subnets (with NAT gateway)
- Terraform >= 1.0
- Docker (for building and pushing image)

## Architecture

- **ECS Cluster**: Fargate cluster for container orchestration
- **ECS Service**: Single-task service (for SQLite simplicity)
- **Task Definition**: 2 vCPU, 4GB memory
- **ECR Repository**: Private Docker registry for TerraFix image
- **Secrets Manager**: Secure storage for Vanta and GitHub tokens
- **CloudWatch Logs**: Structured JSON logs with 30-day retention
- **IAM Roles**: Least-privilege access to Bedrock and logs
- **Security Group**: Outbound-only (for API calls)

## SQLite State Limitations

**Important**: SQLite database is stored in `/tmp/terrafix.db` within the container, making state **ephemeral per task**. When the ECS task restarts (for updates, crashes, or scaling), all processed failure records are lost.

### Implications

- Duplicate PR creation is possible after task restarts
- Processing history is not preserved across deployments
- Statistics are reset on each task start

### Future Enhancement

To persist state across task restarts, mount an EFS volume:

```hcl
resource "aws_efs_file_system" "terrafix_state" {
  # ... EFS configuration ...
}

# Add to task definition:
volume {
  name = "terrafix-state"
  efs_volume_configuration {
    file_system_id = aws_efs_file_system.terrafix_state.id
    root_directory = "/"
  }
}

# Update SQLITE_PATH to /mnt/efs/terrafix.db
```

## Deployment

### 1. Build and Push Docker Image

```bash
# Authenticate with ECR
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-west-2.amazonaws.com

# Build image
docker build -t terrafix:latest .

# Tag for ECR
docker tag terrafix:latest <account-id>.dkr.ecr.us-west-2.amazonaws.com/terrafix-prod:latest

# Push to ECR
docker push <account-id>.dkr.ecr.us-west-2.amazonaws.com/terrafix-prod:latest
```

### 2. Initialize Terraform

```bash
cd terraform
terraform init
```

### 3. Configure Variables

Create `terraform.tfvars`:

```hcl
aws_region = "us-west-2"
environment = "prod"

# Credentials (sensitive)
vanta_api_token = "vanta_oauth_token_here"
github_token = "ghp_github_token_here"

# Networking (from existing VPC)
vpc_id = "vpc-xxxxx"
subnet_ids = ["subnet-xxxxx", "subnet-yyyyy"]

# Configuration
github_repo_mapping = jsonencode({
  default = "myorg/terraform-repo"
})
terraform_path = "terraform"
poll_interval_seconds = 300
```

### 4. Deploy Infrastructure

```bash
terraform plan
terraform apply
```

### 5. Monitor Deployment

```bash
# View logs
aws logs tail /ecs/terrafix-prod --follow

# Check task status
aws ecs describe-services \
  --cluster terrafix-prod \
  --services terrafix-prod
```

## Configuration

### Environment Variables

Configured in `ecs.tf` task definition:

- `VANTA_API_TOKEN`: From Secrets Manager
- `GITHUB_TOKEN`: From Secrets Manager
- `AWS_REGION`: us-west-2
- `BEDROCK_MODEL_ID`: anthropic.claude-sonnet-4-5-v2:0
- `POLL_INTERVAL_SECONDS`: 300 (5 minutes)
- `SQLITE_PATH`: /tmp/terrafix.db (ephemeral)
- `LOG_LEVEL`: INFO
- `GITHUB_REPO_MAPPING`: JSON mapping
- `TERRAFORM_PATH`: Path to .tf files in repos
- `MAX_CONCURRENT_WORKERS`: 3
- `STATE_RETENTION_DAYS`: 7

### Resource Sizing

Default: 2 vCPU, 4GB memory

Adjust in `terraform.tfvars`:

```hcl
cpu = 2048    # 1024 = 1 vCPU
memory = 4096 # In MB
```

### Monitoring

CloudWatch alarm triggers when task count < 1:

- Evaluation: 2 periods of 5 minutes
- Action: (Configure SNS topic for notifications)

## Operations

### Update Application

```bash
# Build and push new image
docker build -t terrafix:latest .
docker tag terrafix:latest <ecr-url>:latest
docker push <ecr-url>:latest

# Force new deployment
aws ecs update-service \
  --cluster terrafix-prod \
  --service terrafix-prod \
  --force-new-deployment
```

### View Logs

```bash
# Tail logs
aws logs tail /ecs/terrafix-prod --follow

# Query logs (CloudWatch Insights)
aws logs start-query \
  --log-group-name /ecs/terrafix-prod \
  --start-time $(date -u -d '1 hour ago' +%s) \
  --end-time $(date -u +%s) \
  --query-string 'fields @timestamp, message | filter level = "ERROR" | sort @timestamp desc'
```

### Troubleshooting

**Task not starting:**
- Check IAM roles have correct permissions
- Verify Secrets Manager secrets exist
- Review CloudWatch logs for startup errors

**No failures being processed:**
- Verify Vanta API token is valid
- Check `GITHUB_REPO_MAPPING` configuration
- Ensure Bedrock model access in us-west-2
- Review logs for API errors

**Duplicate PRs after restart:**
- Expected behavior with ephemeral SQLite
- Consider implementing EFS volume (see above)

## Security

- Credentials stored in AWS Secrets Manager
- Task runs as non-root user
- Security group allows only outbound traffic
- IAM roles follow least-privilege principle
- ECR scans images on push
- CloudWatch Logs encrypted at rest

## Cost Estimate

**Monthly Cost (us-west-2):**
- Fargate (2 vCPU, 4GB, 24/7): ~$60
- CloudWatch Logs (10 GB/month): ~$5
- Bedrock (Claude Sonnet 4.5): Variable (per-token pricing)
- Secrets Manager (2 secrets): ~$1
- ECR storage (< 10 images): ~$0.10

**Total**: ~$66/month + Bedrock usage

## Cleanup

```bash
terraform destroy
```

**Warning**: This will delete all infrastructure including logs and secrets.

