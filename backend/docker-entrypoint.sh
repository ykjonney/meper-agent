#!/bin/bash
set -e

# Fix permissions on mounted volumes at runtime
# This runs as root before switching to appuser
if [ -d "/data/workspaces" ]; then
    chown -R appuser:appuser /data/workspaces 2>/dev/null || true
fi

if [ -d "/data/skills" ]; then
    chown -R appuser:appuser /data/skills 2>/dev/null || true
fi

if [ -d "/app/logs" ]; then
    chown -R appuser:appuser /app/logs 2>/dev/null || true
fi

# Execute the main command as appuser
exec gosu appuser "$@"
