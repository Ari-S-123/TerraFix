# TerraFix Dockerfile for ECS/Fargate deployment
# Python 3.14 base image
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Install system dependencies and Terraform from HashiCorp's official APT repository
# Terraform is NOT available in default Debian repos; it must be installed from HashiCorp
# NOTE: software-properties-common is Ubuntu-specific and NOT available in Debian.
#       It's also not needed since we manually add the repo file instead of using add-apt-repository.
# NOTE: Debian Trixie (13) may not have HashiCorp packages yet, so we fall back to bookworm if needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gnupg \
    curl \
    ca-certificates \
    && curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg \
    && CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME") \
    && if ! curl -fsSL "https://apt.releases.hashicorp.com/dists/${CODENAME}/Release" > /dev/null 2>&1; then \
         CODENAME="bookworm"; \
       fi \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com ${CODENAME} main" > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends terraform \
    && apt-get clean \
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

