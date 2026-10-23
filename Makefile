.PHONY: install dev dev-sandbox dev-local test lint build build-sandbox deploy deploy-check generate-api build-backend-bin build-release clean-dist help

# Default target
help:
	@echo "Available commands:"
	@echo "  make install        - Install all project dependencies"
	@echo "  make dev            - Start development environment (Docker, sandbox disabled)"
	@echo "  make dev-sandbox    - Start development environment with sandbox enabled"
	@echo "  make dev-local      - Start all services locally (FastAPI + Celery + Frontend)"
	@echo "  make test           - Run all tests"
	@echo "  make lint           - Run linters for all packages"
	@echo "  make build          - Build all Docker images (excluding sandbox)"
	@echo "  make build-sandbox  - Build the agent-sandbox image (required for sandboxed bash execution)"
	@echo "  make build-backend-bin - Cython 编译产物（容器内；RELEASE=1 时为正式构建）"
	@echo "  make build-release VERSION=x.y.z [RELEASE=1] - 组装单机安装包 .zip（RELEASE=1 正式/license 强制）"
	@echo "    （每个 <版本-平台> 独立目录 dist/agent-flow-<ver>-<plat>/；rebuild 同 ver-plat 覆盖）"
	@echo "  make clean-dist      - 清空 dist/ 下所有 build 产物（agent-flow-* 目录与 zip）"
	@echo "  make deploy         - Deploy with Docker Compose (production)"
	@echo "  make deploy-check   - Verify sandbox image exists before deploying"
	@echo "  make generate-api   - Generate OpenAPI types from backend spec"

# Install all project dependencies
install:
	cd backend && uv sync && cd ../frontend && npm install && cd ../frontend-client && npm install

# Start development environment (sandbox disabled, bash runs via subprocess)
dev:
	docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build

# Start development environment with sandbox enabled
# Requires the agent-sandbox image to be built first (run make build-sandbox)
dev-sandbox: build-sandbox
	SANDBOX_ENABLED=true docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build

# Start all services locally in one terminal (Ctrl+C stops all)
dev-local:
	@echo "Starting local dev: FastAPI :8000 + Celery worker/beat + Frontend :5173 + Client :3002"
	@trap 'kill 0' EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log) & \
	(cd backend && uv run celery -A app.workers.celery_app worker --loglevel=info --concurrency=2) & \
	(cd backend && uv run celery -A app.workers.celery_app beat --loglevel=info) & \
 	(cd frontend && npm run dev) & \
	(cd frontend-studio && npm run dev) & \
	(cd frontend-client && npm run dev) & \
	wait

# Run all tests
test:
	cd backend && uv run pytest && cd ../frontend && npm run test

# Run linters for all packages
lint:
	cd backend && uv run ruff check . && uv run mypy app && cd ../frontend && npm run lint

# Build all primary Docker images (backend, caddy, etc.)
# NOTE: This does NOT build the sandbox image because it has `profiles: [tools]`.
# Run `make build-sandbox` separately if you need sandboxed bash execution.
build:
	docker compose -f deploy/docker-compose.yml build

# Build the agent-sandbox image.
# Required for sandboxed execution of Agent bash commands (SANDBOX_ENABLED=true).
# Without this image, bash commands silently fall back to insecure subprocess execution.
build-sandbox:
	docker compose -f deploy/docker-compose.yml build sandbox

# 交付包构建入口：交互选择本机/Docker 与目标平台（前端+后端全流程一条命令）。
# 产物 dist/agent-flow-<版本>-<平台>.zip，包内含部署指南。
#   RELEASE=1           正式构建（license 编译期强制）；缺省 dev 构建
#   正式构建（license 强制）加 RELEASE=1；缺省 dev 构建。非交互：-local / -docker（CI 用）
RELEASE_FLAG = $(if $(RELEASE),--release,)
build-release:
	backend/scripts/build_release.sh "$(VERSION)" $(RELEASE_FLAG)

build-release-local:
	backend/scripts/build_release.sh "$(VERSION)" $(RELEASE_FLAG) --local

build-release-docker:  # 平台默认 linux/amd64；加 PLATFORM=linux/arm64 覆盖
	backend/scripts/build_release.sh "$(VERSION)" $(RELEASE_FLAG) --docker --platform $(or $(PLATFORM),linux/amd64)

# 一键清空所有 build 产物（含所有 <版本-平台> 的目录与 zip、wheels-、老式 dist/agent-flow/ 孤儿）
clean-dist:
	rm -rf dist/agent-flow-* dist/agent-flow-wheels-* 2>/dev/null || true
	@echo "✓ dist/ 已清空（保留 dist/ 本身以便 git 跟踪）"

# Deploy instructions (production)
deploy:
	@echo "⚠️  Before deploying, ensure the sandbox image is built (make build-sandbox)."
	@echo "Run: cd deploy && docker compose pull && docker compose up -d"

# Verify sandbox image exists locally (recommended before production deploy)
deploy-check:
	@docker image inspect agent-sandbox:latest >/dev/null 2>&1 \
		&& echo "✅ agent-sandbox:latest image found" \
		|| { echo "❌ agent-sandbox:latest NOT found. Run: make build-sandbox"; exit 1; }

# Generate OpenAPI types from backend spec
generate-api:
	cd backend && uv run python scripts/generate_openapi.py && cd ../frontend && npx openapi-typescript ../backend/openapi.json -o src/types/api.ts
