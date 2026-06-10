#!/usr/bin/env bash
# Tail logs from all services
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f --tail=100
