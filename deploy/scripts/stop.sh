#!/usr/bin/env bash
# Stop the development environment
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
echo "Development environment stopped."
