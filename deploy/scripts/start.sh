#!/usr/bin/env bash
# Start the development environment
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
echo "Development environment started. Logs: ./logs.sh"
