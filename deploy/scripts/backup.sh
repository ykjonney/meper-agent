#!/usr/bin/env bash
# Backup MongoDB data to a compressed archive
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/../backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/mongodb_backup_$TIMESTAMP.tar.gz"

docker compose -f "$SCRIPT_DIR/../docker-compose.yml" exec -T mongodb mongodump --archive --gzip > "$BACKUP_FILE"
echo "MongoDB backup saved to: $BACKUP_FILE"
