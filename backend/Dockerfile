# syntax=docker/dockerfile:1.7

# --- Builder stage: use uv to install prod deps in a slim venv ---
FROM python:3.12-slim AS builder

# Install uv via pip (avoids ghcr.io network issues)
RUN pip install --no-cache-dir uv

WORKDIR /app

# Leverage layer caching: copy lockfiles first
COPY pyproject.toml uv.lock .python-version ./

# Install production dependencies into the project virtualenv (no dev, no project itself yet)
RUN uv sync --frozen --no-dev --no-install-project

# --- Runtime stage: minimal image with non-root user ---
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install gosu for user switching at runtime
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy the venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app/ app/
COPY scripts/ scripts/
COPY pyproject.toml uv.lock .python-version ./

# Create logs directory and data directories for non-root user
RUN mkdir -p /app/logs /data/workspaces /data/skills \
    && chown -R appuser:appuser /app /data

# Ensure the venv takes precedence on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Healthcheck against the unauthenticated /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx, sys; sys.exit(0 if httpx.get('http://localhost:8000/health', timeout=3).status_code == 200 else 1)"

# Fix volume permissions at startup, then run as appuser
CMD chown -R appuser:appuser /data/workspaces /data/skills /app/logs 2>/dev/null || true; \
    exec gosu appuser uvicorn app.main:app --host 0.0.0.0 --port 8000
