# TerraFix Dockerfile for ECS/Fargate deployment
# Python 3.14 base image
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    terraform \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY pyproject.toml .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash terrafix && \
    chown -R terrafix:terrafix /app

# Switch to non-root user
USER terrafix

# Set Python path
ENV PYTHONPATH=/app/src:$PYTHONPATH

# Health check (optional, requires health endpoint)
# HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
#   CMD python -c "import sys; sys.exit(0)"

# Run service
CMD ["python", "-m", "terrafix.service"]

