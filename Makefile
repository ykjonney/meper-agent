.PHONY: install dev test lint build deploy generate-api help

# Default target
help:
	@echo "Available commands:"
	@echo "  make install       - Install all project dependencies"
	@echo "  make dev           - Start development environment"
	@echo "  make test          - Run all tests"
	@echo "  make lint          - Run linters for all packages"
	@echo "  make build         - Build Docker images"
	@echo "  make deploy        - Deploy with Docker Compose"
	@echo "  make generate-api  - Generate OpenAPI types from backend spec"

# Install all project dependencies
install:
	cd backend && uv sync && cd ../frontend && npm install

# Start development environment
dev:
	docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build

# Run all tests
test:
	cd backend && uv run pytest && cd ../frontend && npm run test

# Run linters for all packages
lint:
	cd backend && uv run ruff check . && uv run mypy app && cd ../frontend && npm run lint

# Build Docker images
build:
	docker compose -f deploy/docker-compose.yml build

# Deploy instructions
deploy:
	@echo "Run: docker compose -f deploy/docker-compose.yml pull && docker compose -f deploy/docker-compose.yml up -d"

# Generate OpenAPI types from backend spec
generate-api:
	cd backend && uv run python scripts/generate_openapi.py && cd ../frontend && npx openapi-typescript ../backend/openapi.json -o src/types/api.ts
