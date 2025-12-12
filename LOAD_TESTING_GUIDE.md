# TerraFix Load Testing Guide

This guide provides comprehensive, step-by-step instructions for setting up and running TerraFix load testing experiments using LocalStack and local development tools.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Quick Start](#quick-start)
5. [Detailed Setup](#detailed-setup)
6. [Running Experiments](#running-experiments)
7. [Experiment Types](#experiment-types)
8. [Analyzing Results](#analyzing-results)
9. [Advanced Configuration](#advanced-configuration)
10. [Troubleshooting](#troubleshooting)
11. [LocalStack vs AWS Comparison](#localstack-vs-aws-comparison)

---

## Overview

TerraFix includes a comprehensive load testing harness that measures:

- **Pipeline Throughput**: Maximum sustainable request rate and bottleneck identification
- **Resilience**: Behavior under burst loads, failure injection, and deduplication verification
- **Scalability**: Performance across small, medium, and large repository sizes

### Why LocalStack?

LocalStack provides a local AWS cloud emulation that enables:

- **Cost Savings**: No AWS charges for testing
- **Speed**: Lower latency, faster iteration cycles
- **Reproducibility**: Consistent local environment
- **Offline Development**: No internet connection required

**Important Limitation**: AWS Bedrock (used by TerraFix for Claude AI) is **not supported** by LocalStack. Therefore, load testing uses TerraFix's built-in **mock mode** which simulates the entire remediation pipeline without requiring real AWS Bedrock, Vanta, or GitHub APIs. This would've been the slowest and most expensive part of the whole pipeline because SOTA Reasoning models are slow and expensive so this was a necessary compromise.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Load Testing Environment                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐     ┌───────────────────┐     ┌─────────────┐ │
│  │   Locust    │────▶│  TerraFix API     │────▶│    Redis    │ │
│  │ Load Tester │     │  (Mock Mode)      │     │ State Store │ │
│  └─────────────┘     └───────────────────┘     └─────────────┘ │
│        │                      │                                  │
│        ▼                      ▼                                  │
│  ┌─────────────┐     ┌───────────────────┐                      │
│  │   Results   │     │   LocalStack      │                      │
│  │  CSV/HTML   │     │  (S3, IAM, etc.)  │                      │
│  └─────────────┘     └───────────────────┘                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Purpose | Port |
|-----------|---------|------|
| **TerraFix API** | HTTP webhook server in mock mode | 8081 |
| **Redis** | State store for failure deduplication | 6379 |
| **LocalStack** | AWS service emulation (optional for load tests) | 4566 |
| **Locust** | Load testing framework | 8089 (web UI) |

---

## Prerequisites

### Required Software

1. **Docker** (with Docker Compose)
   - Windows: [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/)
   - macOS: [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/)
   - Linux: [Docker Engine](https://docs.docker.com/engine/install/)

2. **Python 3.11+** (Python 3.14 recommended)
   - Download from [python.org](https://www.python.org/downloads/)

3. **Git** (for cloning the repository)

### Verify Installation

```bash
# Check Docker
docker --version
docker compose version

# Check Python
python --version
# or
python3 --version

# Check Git
git --version
```

---

## Quick Start

### Option 1: Using the Load Test Script (Recommended)

**Linux/macOS:**

```bash
# Make script executable
chmod +x scripts/run_load_tests.sh

# Start environment and run all experiments
./scripts/run_load_tests.sh all
```

**Windows (PowerShell):**

```powershell
# Run all experiments
.\scripts\run_load_tests.ps1 all
```

### Option 2: Manual Step-by-Step

```bash
# 1. Start the environment
docker-compose -f docker-compose.localstack.yml up -d

# 2. Wait for services to be ready
curl http://localhost:8081/health

# 3. Install Python dependencies
pip install -r requirements-dev.txt

# 4. Run load tests
python -m terrafix.experiments.run_experiments --local

# 5. View results
# Open experiment_results/experiment_summary.html in a browser

# 6. Stop environment when done
docker-compose -f docker-compose.localstack.yml down
```

---

## Detailed Setup

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-org/terrafix.git
cd terrafix
```

### Step 2: Create Python Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
# Linux/macOS:
source venv/bin/activate
# Windows:
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Step 3: Configure Environment Variables

Copy the example environment file:

```bash
cp env.localstack.example .env
```

Key configuration options in `.env`:

```bash
# Mock mode settings
TERRAFIX_MOCK_MODE=true
MOCK_LATENCY_MS=50          # Simulated processing time
MOCK_FAILURE_RATE=0.0       # Simulated failure rate

# Redis connection
REDIS_URL=redis://localhost:6379/0

# Experiment settings
TERRAFIX_EXPERIMENT=throughput
```

### Step 4: Start Docker Services

```bash
# Start all services (LocalStack, Redis, TerraFix API)
docker-compose -f docker-compose.localstack.yml up -d

# Verify services are running
docker-compose -f docker-compose.localstack.yml ps

# Check health endpoints
curl http://localhost:8081/health    # TerraFix API
curl http://localhost:4566/_localstack/health  # LocalStack
docker exec terrafix-redis redis-cli ping  # Redis
```

### Step 5: Verify Setup

```bash
# Check TerraFix API status
curl http://localhost:8081/status | python -m json.tool

# Expected output:
# {
#     "status": "running",
#     "mock_mode": true,
#     "stats": {
#         "total_requests": 0,
#         "successful_requests": 0,
#         ...
#     }
# }
```

---

## Running Experiments

### Method 1: Automated Runner (Recommended)

The automated runner executes all three experiment types sequentially:

```bash
# Run all experiments
python -m terrafix.experiments.run_experiments --local

# Run specific experiment
python -m terrafix.experiments.run_experiments --local --experiment throughput

# Custom output directory
python -m terrafix.experiments.run_experiments --local --output ./my_results
```

### Method 2: Using Helper Scripts

**Linux/macOS:**

```bash
# Start environment
./scripts/run_load_tests.sh start

# Run throughput test
./scripts/run_load_tests.sh test --experiment throughput

# Run with custom parameters
./scripts/run_load_tests.sh test --experiment resilience --users 30 --duration 10m

# Interactive Locust UI
./scripts/run_load_tests.sh test --locust-ui

# Stop environment
./scripts/run_load_tests.sh stop
```

**Windows (PowerShell):**

```powershell
# Start environment
.\scripts\run_load_tests.ps1 start

# Run throughput test
.\scripts\run_load_tests.ps1 test -Experiment throughput

# Run with custom parameters
.\scripts\run_load_tests.ps1 test -Experiment resilience -Users 30 -Duration "10m"

# Interactive Locust UI
.\scripts\run_load_tests.ps1 test -LocustUI

# Stop environment
.\scripts\run_load_tests.ps1 stop
```

### Method 3: Direct Locust Commands

For maximum control, run Locust directly:

```bash
# Navigate to experiments directory
cd src/terrafix/experiments

# Run with web UI (interactive)
locust -f locustfile.py --host=http://localhost:8081
# Then open http://localhost:8089 in browser

# Run headless (automated)
TERRAFIX_EXPERIMENT=throughput locust -f locustfile.py \
    --host=http://localhost:8081 \
    --headless \
    --users 50 \
    --spawn-rate 5 \
    --run-time 5m \
    --csv=results/throughput \
    --html=results/throughput_report.html
```

### Method 4: Using Docker Locust Container

```bash
# Start with Locust container
docker-compose -f docker-compose.localstack.yml --profile loadtest up -d

# Access Locust web UI
# Open http://localhost:8089 in browser
```

---

## Experiment Types

### 1. Throughput Experiment

Measures maximum sustainable throughput and identifies bottlenecks.

| Phase | Users | Duration | Purpose |
|-------|-------|----------|---------|
| Baseline | 5 | 3 min | Establish baseline latency |
| Medium | 20 | 5 min | Moderate load |
| High | 50 | 5 min | High throughput |
| Maximum | 100 | 5 min | Find limits |

**Metrics Collected:**
- Requests per second
- P50, P95, P99 latencies
- Error rates
- Bottleneck identification

```bash
# Run throughput experiment
python -m terrafix.experiments.run_experiments --local --experiment throughput
```

### 2. Resilience Experiment

Tests system behavior under stress and failure conditions.

| Phase | Type | Users | Duration | Purpose |
|-------|------|-------|----------|---------|
| Steady State | ResilienceUser | 10 | 5 min | Baseline with deduplication |
| Burst | BurstUser | 30 | 5 min | Sudden load spikes |
| Cascade | CascadeUser | 50 | 10 min | Exponentially increasing |
| Failures | MixedUser | 20 | 5 min | With 10% failure injection |

**Metrics Collected:**
- Deduplication effectiveness
- Retry success rates
- Recovery time
- Error handling

```bash
# Run resilience experiment
python -m terrafix.experiments.run_experiments --local --experiment resilience

# Or with failure injection
MOCK_FAILURE_RATE=0.1 ./scripts/run_load_tests.sh test --experiment resilience
```

### 3. Scalability Experiment

Tests performance across different repository sizes.

| Phase | Repository Size | Resources | Duration |
|-------|-----------------|-----------|----------|
| Small | 5-15 | Simple configs | 3 min |
| Medium | 50-100 | Multi-service | 3 min |
| Large | 300+ | Enterprise-scale | 3 min |
| Mixed | Varied | Random mix | 5 min |

**Metrics Collected:**
- Parsing time vs complexity
- Memory consumption patterns
- Response time correlation with size

```bash
# Run scalability experiment
python -m terrafix.experiments.run_experiments --local --experiment scalability

# Test specific size
TERRAFIX_REPO_SIZE=large locust -f locustfile.py --host=http://localhost:8081 --headless --users 10 --run-time 3m
```

---

## Analyzing Results

### Output Files

After running experiments, results are saved in `experiment_results/`:

```
experiment_results/
├── throughput/
│   ├── throughput_baseline_stats.csv
│   ├── throughput_baseline_report.html
│   ├── throughput_medium_stats.csv
│   └── ...
├── resilience/
│   └── ...
├── scalability/
│   └── ...
├── experiment_summary.json
├── experiment_summary.html
├── charts/
│   ├── latency_distribution.png
│   ├── percentile_chart.png
│   ├── throughput_timeline.png
│   └── success_failure_rate.png
└── charts_report.html
```

### Viewing Results

```bash
# Open HTML summary in browser
# Linux
xdg-open experiment_results/experiment_summary.html

# macOS
open experiment_results/experiment_summary.html

# Windows
start experiment_results\experiment_summary.html
```

### Key Metrics to Analyze

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| P50 Latency | < 100ms | 100-500ms | > 500ms |
| P99 Latency | < 1s | 1-5s | > 5s |
| Success Rate | > 99% | 95-99% | < 95% |
| Throughput | Stable | Fluctuating | Declining |

### Real-Time Monitoring

While tests are running:

```bash
# Check API server stats
curl http://localhost:8081/status | python -m json.tool

# Watch Redis state
docker exec terrafix-redis redis-cli info stats

# View live logs
docker-compose -f docker-compose.localstack.yml logs -f terrafix-api
```

---

## Advanced Configuration

### Customizing Mock Behavior

Adjust the mock processor to simulate different conditions:

```bash
# Higher latency (simulating Bedrock response time)
MOCK_LATENCY_MS=500 docker-compose -f docker-compose.localstack.yml up -d terrafix-api

# Introduce failures
MOCK_FAILURE_RATE=0.2 docker-compose -f docker-compose.localstack.yml up -d terrafix-api
```

Or configure at runtime:

```bash
curl -X POST http://localhost:8081/configure \
  -H "Content-Type: application/json" \
  -d '{"latency_ms": 200, "failure_rate": 0.1}'
```

### Custom Experiment Profiles

Create custom experiment configurations by modifying `src/terrafix/experiments/run_experiments.py`:

```python
# Add custom experiment in EXPERIMENTS dict
"custom_burst": [
    ExperimentConfig(
        name="custom_burst_test",
        description="Custom burst test with specific parameters",
        locust_class="burst",
        users=100,
        spawn_rate=20,
        run_time="2m",
    ),
]
```

### Using LocalStack for Infrastructure Testing

While load tests use mock mode, LocalStack can test Terraform infrastructure:

```bash
# Configure AWS CLI for LocalStack
aws configure --profile localstack
# Access Key ID: test
# Secret Access Key: test
# Region: us-west-2
# Output: json

# Create S3 bucket in LocalStack
aws --endpoint-url=http://localhost:4566 --profile localstack \
  s3 mb s3://test-bucket

# List LocalStack resources
aws --endpoint-url=http://localhost:4566 --profile localstack \
  s3 ls
```

### Running Against Deployed Service

To test against an actual TerraFix deployment:

```bash
# Test against deployed AWS service
python -m terrafix.experiments.run_experiments \
  --host https://your-terrafix.amazonaws.com:8081 \
  --experiment throughput

# Note: This will use real Bedrock, GitHub, and Vanta APIs
# Ensure proper credentials are configured
```

---

## Troubleshooting

### Common Issues

#### 1. Docker Services Won't Start

```bash
# Check Docker is running
docker ps

# View service logs
docker-compose -f docker-compose.localstack.yml logs

# Restart with clean state
docker-compose -f docker-compose.localstack.yml down -v
docker-compose -f docker-compose.localstack.yml up -d
```

#### 2. API Server Not Responding

```bash
# Check if port is in use
# Linux/macOS
lsof -i :8081
# Windows
netstat -ano | findstr :8081

# Check container health
docker inspect terrafix-api --format='{{.State.Health.Status}}'

# View API server logs
docker logs terrafix-api
```

#### 3. Redis Connection Failed

```bash
# Test Redis connectivity
docker exec terrafix-redis redis-cli ping

# Check Redis logs
docker logs terrafix-redis

# Verify Redis URL
echo $REDIS_URL
```

#### 4. Locust Not Found

```bash
# Install Locust
pip install locust

# Verify installation
locust --version
```

#### 5. LocalStack Health Check Fails

```bash
# Check LocalStack logs
docker logs terrafix-localstack

# Restart LocalStack
docker-compose -f docker-compose.localstack.yml restart localstack

# Note: LocalStack is optional for load testing (mock mode doesn't use it)
```

### Performance Issues

#### High Latency

1. Check `MOCK_LATENCY_MS` setting
2. Verify Docker has sufficient resources
3. Reduce number of concurrent users

#### Out of Memory

```bash
# Increase Docker memory limits
# Edit docker-compose.localstack.yml:
services:
  terrafix-api:
    deploy:
      resources:
        limits:
          memory: 2G
```

### Cleaning Up

```bash
# Stop all services
docker-compose -f docker-compose.localstack.yml down

# Remove volumes (reset state)
docker-compose -f docker-compose.localstack.yml down -v

# Full cleanup
./scripts/run_load_tests.sh clean
```

---

## References

- [Locust Documentation](https://docs.locust.io/)
- [LocalStack Documentation](https://docs.localstack.cloud/)
- [TerraFix README](./README.md)
- [TerraFix Deployment Guide](./DEPLOYMENT_GUIDE.md)
- [Developer Activity Pulse (LocalStack example)](https://github.com/Ari-S-123/developer-activity-pulse)

