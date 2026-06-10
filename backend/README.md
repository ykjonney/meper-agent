# Agent Flow Backend

FastAPI + LangGraph + MongoDB + Celery + Redis backend for the Agent Flow platform.

## Tech Stack

- **Python**: 3.12
- **Framework**: FastAPI 0.128+
- **AI Engine**: LangGraph 1.0.8+
- **Database**: MongoDB 7.0
- **Cache/Broker**: Redis 7
- **Task Queue**: Celery 5.4+
- **Package Manager**: uv (NOT pip/poetry/pipenv)

## Quick Start

```bash
# Install dependencies
uv sync

# Run development server
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
uv run pytest

# Lint
uv run ruff check .
uv run mypy app
```

## Project Structure

```
app/
├── api/           # Route layer (api/middleware, api/v1)
├── core/          # Core: config, security, logging, errors
├── models/        # MongoDB data models
├── schemas/       # Pydantic request/response
├── services/      # Business logic layer
├── engine/        # LangGraph engine
├── workers/       # Celery tasks
└── db/            # MongoDB/Redis connections
```

## API Documentation

- Swagger UI: `http://localhost:8000/api/v1/docs`
- ReDoc: `http://localhost:8000/api/v1/redoc`
- OpenAPI JSON: `http://localhost:8000/api/v1/openapi.json`
