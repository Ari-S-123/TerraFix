# TerraFix: AI-Powered Terraform Compliance Remediation Bot

**TerraFix** is a long-running service that automatically detects Vanta compliance failures, analyzes Terraform configurations, generates compliant fixes using Claude Opus 4.5 via AWS Bedrock, and opens GitHub Pull Requests for human review.

## Architecture

```
Vanta Platform → TerraFix Worker → AWS Bedrock Claude → GitHub PR
                       ↓
                 Redis State Store
                       ↓
               Health Check (HTTP)
```

**Key Differentiator**: Human-in-the-loop architecture. No direct AWS access required. This is meant to work at the Infrastructure-as-Code layer where changes belong, not directly on cloud resources.

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

- **Python 3.14**
- **AWS Account** with Bedrock access
- **Vanta Account** with API access (OAuth token with `vanta-api.all:read`)
- **GitHub Account** with Personal Access Token (repo scope)
- **Redis** endpoint

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
export BEDROCK_MODEL_ID="anthropic.claude-opus-4-5-20251101-v1:0"
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

Terraform modules to deploy TerraFix as a single-task Fargate service:

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

- **Terraform-Only**: Currently only supports Terraform (CloudFormation/Pulumi support could be added later)
- **Polling-Based**: 5-minute polling interval (Vanta webhooks not available)
- **No Terraform Plan**: Runs `terraform fmt` and `terraform validate`; does not run `terraform plan` prior to PR creation
- **Terraform Binary Required for Validation**: If terraform is unavailable, validation falls back to skip with warnings
- **Vanta API Access**: Vanta is an enterprise compliance platform that requires [requesting a demo](https://www.vanta.com/pricing) rather than self-service signup. This means obtaining API credentials for end-to-end testing requires enterprise engagement, which ended up not being feasible within the project timeline. As a result, **full end-to-end testing with the live production Vanta API could not be performed in time for the project submission**. The Vanta client implementation is based on Vanta's public API documentation and mocked unit tests.

## Development

```bash
# Linting
ruff check src/

# Type checking
mypy src/

# Format
ruff format src/

# Run unit tests
pytest tests/unit/ -v

# Run tests with coverage
pytest tests/unit/ --cov=src/terrafix --cov-report=term-missing
```

## Testing

TerraFix includes a comprehensive test suite using pytest with VCR.py for API mocking:

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test module
pytest tests/unit/test_vanta_client.py -v

# Run with coverage report
pytest tests/unit/ --cov=src/terrafix --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Test Fixtures

Sample Terraform configurations are provided in `tests/fixtures/terraform/`:
- `small/` - Minimal 2-resource configuration
- `medium/` - Multi-service setup with S3, IAM, security groups
- `large/` - Enterprise setup with VPC, RDS, comprehensive IAM

## Observability

### Metrics

TerraFix collects metrics via the built-in metrics collector, exposed at `/metrics`:

```bash
# View metrics (when service is running)
curl http://localhost:8080/metrics
```

Available metrics:
- **Counters**: `failures_processed_total`, `prs_created_total`, `api_errors_total`
- **Gauges**: `queue_depth`, `active_workers`
- **Timings**: Per-stage latencies (fetch, clone, analyze, generate, validate, create PR)

### Health Endpoints

- `/health` - Basic health check
- `/ready` - Readiness probe (checks Redis connectivity)
- `/status` - Detailed status with component health
- `/metrics` - JSON metrics endpoint

## Experiment Harness

TerraFix includes a comprehensive experiment harness for performance testing and benchmarking, featuring both in-process experiments and Locust-based load testing against deployed services.

### In-Process Experiments

```bash
# Run throughput experiment
python -m terrafix.experiments run --type throughput --preset baseline

# Run stress test with burst workload
python -m terrafix.experiments run --type throughput --preset stress_test

# Run resilience test with failure injection
python -m terrafix.experiments run --type resilience --failure-rate 0.2

# Run scalability test across repo sizes
python -m terrafix.experiments run --type scalability

# List available presets
python -m terrafix.experiments list-presets
```

### Locust Load Testing (Recommended for Deployed Services)

For load testing against actual deployed TerraFix instances, we provide Locust-based tests:

```bash
# Start the mock API server for local testing
TERRAFIX_MOCK_MODE=true python -m terrafix.api_server

# Run Locust with web UI (http://localhost:8089)
cd src/terrafix/experiments
locust -f locustfile.py --host=http://localhost:8081

# Run headless throughput test
TERRAFIX_EXPERIMENT=throughput locust -f locustfile.py \
    --host=http://localhost:8081 --headless \
    --users 50 --spawn-rate 5 --run-time 5m --csv=results

# Run all experiments with automated runner
python -m terrafix.experiments.run_experiments --local

# Run against deployed AWS service
python -m terrafix.experiments.run_experiments \
    --host https://your-terrafix.amazonaws.com:8081
```

### Experiment Types

The load testing implements the three experiments from the specification:

1. **Throughput**: Measure maximum sustainable throughput, P50/P95/P99 latencies
2. **Resilience**: Test steady-state, burst, and cascade workloads with deduplication verification
3. **Scalability**: Test with small/medium/large repository profiles

### Workload Profiles

- **STEADY_STATE**: Constant rate of failures (baseline testing)
- **BURST**: Periodic high-volume spikes (stress testing)
- **CASCADE**: Exponentially increasing load (finding limits)
- **MIXED**: Production-like traffic patterns

### Chart Generation

After running experiments, generate visualization charts:

```bash
# Charts are auto-generated in experiment results directory
# Or manually generate from CSV/JSON results
python -c "
from terrafix.experiments.charts import generate_report_from_files
generate_report_from_files(['results_stats.csv'], 'charts/', html=True)
"
```

Available charts: latency distribution, percentile plots, throughput timeline, success/failure rates, comparison charts, and HTML reports.

## CI/CD

TerraFix uses GitHub Actions for continuous integration:

- **Linting**: Ruff check and format verification
- **Type Checking**: MyPy strict mode
- **Unit Tests**: Pytest with coverage reporting
- **Coverage**: Uploaded to Codecov

See `.github/workflows/ci.yml` for the full pipeline configuration.

## Future Enhancements

- **Multi-IaC**: CloudFormation, Pulumi, CDK support
- **Deeper Validation**: Run `terraform plan` in isolated environment
- **Cost Analysis**: Integrate Infracost for cost impact estimates
- **Learning from Feedback**: Track accepted/rejected PRs for continuous improvement
- **Richer Webhooks**: Add Vanta webhook support once available to reduce polling latency

## Security

- All credentials stored in AWS Secrets Manager (ECS deployment)
- Least-privilege IAM roles for Bedrock, ElastiCache, and CloudWatch access
- No direct AWS resource modifications (only IaC changes via PRs)
- Structured logs with correlation IDs for audit trails
- Read-only Vanta API access (no write permissions needed)
- Secure Git cloning via credential helper (tokens not exposed in process args)

---

**Built with Python 3.14, Claude Opus 4.5, and a commitment to keeping humans in the loop.**
