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

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy the venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app/ app/
COPY scripts/ scripts/
COPY pyproject.toml uv.lock .python-version ./

# Create logs directory for non-root user
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# Ensure the venv takes precedence on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Switch to non-root
USER appuser

EXPOSE 8000

# Healthcheck against the unauthenticated /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx, sys; sys.exit(0 if httpx.get('http://localhost:8000/health', timeout=3).status_code == 200 else 1)"

# Start Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
