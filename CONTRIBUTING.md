# Contributing to TerraFix

Thank you for your interest in contributing to TerraFix! This document provides guidelines for development, testing, and submitting contributions.

## Development Setup

### Prerequisites

- Python 3.14
- Git
- Docker (optional, for testing containerization)
- Terraform (optional, for infrastructure testing)

### Local Setup

```bash
# Clone repository
git clone https://github.com/your-org/terrafix.git
cd terrafix

# Create virtual environment
python3.14 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install package in development mode
pip install -e .
```

## Code Standards

### Style Guide

TerraFix follows these conventions:

- **PEP 8**: Python code style
- **Type Hints**: All functions must have type annotations
- **Docstrings**: Google-style docstrings for all public APIs
- **Line Length**: 100 characters maximum
- **Imports**: Organized with `ruff` (stdlib, third-party, local)

### Linting and Formatting

```bash
# Run ruff linter
ruff check src/

# Format code
ruff format src/

# Type checking
mypy src/
```

### Documentation

All code must be thoroughly documented:

```python
def process_failure(
    failure: Failure,
    config: Settings,
    state_store: StateStore,
    vanta: VantaClient,
    generator: TerraformRemediationGenerator,
    gh: GitHubPRCreator,
) -> ProcessingResult:
    """
    Process a single compliance failure end-to-end.

    This is the main orchestration function that coordinates:
    1. Deduplication check
    2. Repository cloning
    3. Terraform analysis
    4. Fix generation via Bedrock
    5. Validation and formatting
    6. GitHub PR creation
    7. State tracking

    Args:
        failure: Vanta compliance failure to process
        config: Application settings
        state_store: SQLite state store for deduplication
        vanta: Vanta API client
        generator: Bedrock remediation generator
        gh: GitHub PR creator

    Returns:
        ProcessingResult with success status and details

    Raises:
        TerraFixError: If processing fails permanently

    Example:
        >>> result = process_failure(failure, config, store, vanta, gen, gh)
        >>> if result.success:
        ...     print(f"Created PR: {result.pr_url}")
    """
    # Implementation...
```

## Testing

TerraFix has a comprehensive test suite using pytest with VCR.py for HTTP mocking and fakeredis for Redis mocking.

### Running Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_vanta_client.py -v

# Run specific test class
pytest tests/unit/test_redis_state_store.py::TestCheckAndClaim -v

# Run with coverage report
pytest tests/unit/ --cov=src/terrafix --cov-report=term-missing

# Generate HTML coverage report
pytest tests/unit/ --cov=src/terrafix --cov-report=html
```

### Test Structure

```
tests/
├── conftest.py              # Shared fixtures (mock clients, sample data)
├── fixtures/
│   ├── cassettes/           # VCR.py recorded HTTP interactions
│   └── terraform/           # Sample Terraform configurations
│       ├── small/           # Minimal config for quick tests
│       ├── medium/          # Multi-service setup
│       └── large/           # Enterprise setup for scalability tests
└── unit/
    ├── test_config.py       # Configuration tests
    ├── test_vanta_client.py # Vanta API client tests
    ├── test_terraform_analyzer.py # Terraform parsing tests
    ├── test_remediation_generator.py # Bedrock integration tests
    ├── test_github_pr_creator.py # GitHub PR tests
    ├── test_orchestrator.py # Pipeline orchestration tests
    └── test_redis_state_store.py # Redis state store tests
```

### Writing Tests

Use the provided fixtures from `conftest.py`:

```python
def test_process_failure_success(
    mock_settings: Settings,
    sample_failure: Failure,
    mock_redis_client: MagicMock,
    mock_bedrock_client: MagicMock,
    mock_github_client: MagicMock,
) -> None:
    """Test successful failure processing."""
    # Test implementation using fixtures
    ...
```

### Integration Tests (Future)

```bash
# Run integration tests (requires AWS credentials)
pytest tests/integration/
```

> **⚠️ Note on Vanta Integration Testing**
>
> Full end-to-end testing with the Vanta API is currently **not possible** without enterprise API access. Vanta does not offer self-service signup—you must [request a demo](https://www.vanta.com/pricing) and engage with their sales team to obtain API credentials. This process can take a while.
>
> As a result, Vanta client tests use mocked responses based on [Vanta's public API documentation](https://developer.vanta.com/reference). If you have access to a Vanta enterprise account with API credentials, you can run live integration tests by setting the `VANTA_API_TOKEN` environment variable.

### Manual Testing

```bash
# Create test failure JSON
cat > test_failure.json << EOF
{
  "test_id": "test-123",
  "test_name": "S3 Bucket Block Public Access",
  "resource_arn": "arn:aws:s3:::test-bucket",
  "resource_type": "AWS::S3::Bucket",
  "failure_reason": "Bucket allows public access",
  "severity": "high",
  "framework": "SOC2",
  "failed_at": "2025-11-14T10:00:00Z",
  "current_state": {},
  "required_state": {}
}
EOF

# Process test failure
python -m terrafix.cli process-once --failure-json test_failure.json
```

### Experiment Harness

For performance testing and benchmarking:

```bash
# Run throughput experiment (in-process)
python -m terrafix.experiments run --type throughput --preset baseline

# Run resilience test with 20% failure injection
python -m terrafix.experiments run --type resilience --failure-rate 0.2

# Run scalability test
python -m terrafix.experiments run --type scalability

# List available presets
python -m terrafix.experiments list-presets
```

### Load Testing with Locust

For realistic load testing against deployed services:

```bash
# Start mock API server for local load testing
TERRAFIX_MOCK_MODE=true python -m terrafix.api_server

# Run Locust with web UI (opens http://localhost:8089)
cd src/terrafix/experiments
locust -f locustfile.py --host=http://localhost:8081

# Headless throughput test
TERRAFIX_EXPERIMENT=throughput locust -f locustfile.py \
    --host=http://localhost:8081 --headless \
    --users 50 --spawn-rate 5 --run-time 5m --csv=results

# Run all experiments with automated runner
python -m terrafix.experiments.run_experiments --local

# Run against deployed service
python -m terrafix.experiments.run_experiments \
    --host https://your-terrafix.amazonaws.com:8081
```

#### Experiment Types

- **throughput**: Measure max sustainable throughput, identify bottlenecks
- **resilience**: Test steady-state, burst, cascade workloads
- **scalability**: Test with small/medium/large repository profiles
- **burst**: High-volume spike testing
- **cascade**: Exponentially increasing load

#### Generating Reports

After running experiments, charts and reports are automatically generated:
- `experiment_results/experiment_summary.html` - Summary report
- `experiment_results/charts/` - PNG charts
- `experiment_results/charts_report.html` - Charts with analysis

## Making Changes

### Branch Naming

- `feature/description`: New features
- `fix/description`: Bug fixes
- `docs/description`: Documentation updates
- `refactor/description`: Code refactoring

### Commit Messages

Follow conventional commits format:

```
type(scope): Short description

Longer description if needed explaining the change and why.

Fixes #123
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance

Examples:
```
feat(orchestrator): Add retry logic for transient failures

Implements exponential backoff retry for VantaApiError, BedrockError,
and GitHubError when they are marked as retryable.

Fixes #45
```

## Submitting Changes

### Pull Request Process

1. **Fork** the repository
2. **Create** a feature branch
3. **Make** your changes
4. **Add** tests (when test framework exists)
5. **Update** documentation
6. **Run** linters and type checks
7. **Commit** with conventional commit messages
8. **Push** to your fork
9. **Open** a Pull Request

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Refactoring

## Testing
How was this tested?

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] Tests added/updated (when applicable)
- [ ] Linter and type checker pass
```

## Architecture Guidelines

### Adding New Components

When adding new components:

1. Follow existing patterns in the codebase
2. Add comprehensive docstrings
3. Include proper error handling
4. Use structured logging
5. Add type hints
6. Consider retry logic for external APIs

### Error Handling

All errors must inherit from `TerraFixError`:

```python
class NewError(TerraFixError):
    """
    Description of when this error occurs.

    Attributes:
        specific_field: Description
    """

    def __init__(
        self,
        message: str,
        specific_field: str | None = None,
        retryable: bool = False,
    ) -> None:
        """Initialize error with context."""
        context = {"specific_field": specific_field}
        super().__init__(message, retryable=retryable, context=context)
        self.specific_field = specific_field
```

### Logging

Use structured logging throughout:

```python
from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)

log_with_context(
    logger,
    "info",
    "Processing started",
    test_id=failure.test_id,
    resource_arn=failure.resource_arn,
)
```

## Project Structure

```
terrafix/
├── src/terrafix/              # Source code
│   ├── __init__.py            # Package metadata
│   ├── __main__.py            # Entry point
│   ├── cli.py                 # CLI interface
│   ├── config.py              # Configuration management
│   ├── errors.py              # Exception hierarchy
│   ├── logging_config.py      # Structured logging
│   ├── metrics.py             # Metrics collection system
│   ├── health_check.py        # Health check endpoints
│   ├── rate_limiter.py        # Token bucket rate limiter
│   ├── vanta_client.py        # Vanta API integration
│   ├── terraform_analyzer.py  # Terraform HCL parsing
│   ├── terraform_validator.py # Terraform validation
│   ├── remediation_generator.py # Bedrock Claude integration
│   ├── github_pr_creator.py   # GitHub PR creation
│   ├── secure_git.py          # Secure Git operations
│   ├── redis_state_store.py   # Redis state management
│   ├── state_store.py         # State store interface
│   ├── resource_mappings.py   # AWS to Terraform mappings
│   ├── orchestrator.py        # Main processing pipeline
│   ├── service.py             # Long-running service
│   ├── api_server.py          # Load testing API server
│   └── experiments/           # Experiment harness
│       ├── __init__.py        # Package exports
│       ├── __main__.py        # CLI entry point
│       ├── cli.py             # Experiment CLI
│       ├── profiles.py        # Workload profiles
│       ├── generator.py       # Synthetic failure generator
│       ├── injector.py        # Failure injection
│       ├── reporter.py        # Results reporting
│       ├── runner.py          # Experiment orchestration
│       ├── locustfile.py      # Locust load tests
│       ├── run_experiments.py # Automated experiment runner
│       └── charts.py          # Chart generation
├── tests/                     # Test suite
│   ├── conftest.py            # Shared pytest fixtures
│   ├── fixtures/              # Test data
│   │   ├── cassettes/         # VCR.py HTTP recordings
│   │   └── terraform/         # Sample Terraform configs
│   └── unit/                  # Unit tests
│       ├── test_config.py
│       ├── test_vanta_client.py
│       ├── test_terraform_analyzer.py
│       ├── test_remediation_generator.py
│       ├── test_github_pr_creator.py
│       ├── test_orchestrator.py
│       └── test_redis_state_store.py
├── terraform/                 # Infrastructure as code
├── .github/workflows/         # CI/CD pipelines
│   └── ci.yml                 # GitHub Actions workflow
├── requirements.txt           # Production dependencies
├── requirements-dev.txt       # Development dependencies
├── pyproject.toml             # Python project configuration
├── Dockerfile                 # Container image
├── README.md                  # Main documentation
└── CONTRIBUTING.md            # This file
```

## Code Review Guidelines

When reviewing PRs:

- Check for proper error handling
- Verify type hints are present
- Ensure documentation is complete
- Review security implications
- Test manually if possible
- Check for performance implications

## Questions?

- Open an issue for discussion
- Check existing issues and PRs
- Review documentation in `README.md` and `DEPLOYMENT_GUIDE.md`

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT).

