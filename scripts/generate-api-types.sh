#!/usr/bin/env bash
# Generate TypeScript types from the backend OpenAPI schema
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Generating OpenAPI schema from backend..."
cd "$PROJECT_ROOT/backend"
uv run python scripts/generate_openapi.py

echo "Generating TypeScript types..."
cd "$PROJECT_ROOT/frontend-studio"
npx openapi-typescript ../backend/openapi.json -o src/types/api.ts

echo "Done! Types written to frontend-studio/src/types/api.ts"
