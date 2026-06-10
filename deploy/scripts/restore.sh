#!/usr/bin/env bash
# Restore MongoDB data from a backup archive
# Usage: ./restore.sh <backup_file>
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_FILE="${1:-}"

if [ -z "$BACKUP_FILE" ]; then
  echo "Usage: $0 <backup_file>"
  exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Error: backup file not found: $BACKUP_FILE"
  exit 1
fi

docker compose -f "$SCRIPT_DIR/../docker-compose.yml" exec -T mongodb mongorestore --archive --gzip < "$BACKUP_FILE"
echo "MongoDB restore complete from: $BACKUP_FILE"
