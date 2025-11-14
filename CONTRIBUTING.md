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

### Unit Tests (Future)

```bash
# Run unit tests
pytest tests/unit/

# With coverage
pytest --cov=src/terrafix tests/unit/
```

### Integration Tests (Future)

```bash
# Run integration tests (requires AWS credentials)
pytest tests/integration/
```

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
├── src/terrafix/           # Source code
│   ├── __init__.py         # Package metadata
│   ├── config.py           # Configuration management
│   ├── logging_config.py   # Structured logging
│   ├── errors.py           # Exception hierarchy
│   ├── vanta_client.py     # Vanta API integration
│   ├── terraform_analyzer.py  # Terraform parsing
│   ├── remediation_generator.py  # Bedrock integration
│   ├── github_pr_creator.py  # GitHub PR creation
│   ├── state_store.py      # SQLite state management
│   ├── orchestrator.py     # Main processing pipeline
│   ├── service.py          # Long-running service
│   └── cli.py              # CLI interface
├── tests/                  # Tests (future)
│   ├── unit/
│   └── integration/
├── terraform/              # Infrastructure as code
├── requirements.txt        # Production dependencies
├── requirements-dev.txt    # Development dependencies
├── pyproject.toml          # Python project configuration
├── Dockerfile              # Container image
└── README.md               # Main documentation
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

