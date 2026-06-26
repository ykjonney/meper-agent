#!/usr/bin/env bash
# Pre-commit hook: run linters locally
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Running backend lint..."
cd "$PROJECT_ROOT/backend"
uv run ruff check .

echo "Running frontend-studio lint..."
cd "$PROJECT_ROOT/frontend-studio"
npm run lint

echo "All checks passed!"
