#!/usr/bin/env bash
# One-shot development environment setup
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Agent Flow — Dev Environment Setup ==="
echo ""

# Backend setup
echo "[1/4] Setting up backend (uv)..."
cd "$PROJECT_ROOT/backend"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created backend/.env from .env.example (adjust values if needed)"
fi
uv sync
echo "  Backend dependencies installed."

# Frontend setup
echo "[2/4] Setting up frontend (npm)..."
cd "$PROJECT_ROOT/frontend"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created frontend/.env from .env.example"
fi
npm install
echo "  Frontend dependencies installed."

# Deploy setup
echo "[3/4] Setting up deploy config..."
cd "$PROJECT_ROOT/deploy"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created deploy/.env from .env.example"
  echo "  IMPORTANT: Change JWT_SECRET_KEY and MONGO_ROOT_PASSWORD before production use!"
fi

# Final check
echo "[4/4] Setup complete!"
echo ""
echo "Next steps:"
echo "  - Start dev environment:    make dev"
echo "  - Run tests:                make test"
echo "  - View backend API docs:    http://localhost:8000/api/v1/docs"
echo "  - View frontend:            http://localhost:5173"
