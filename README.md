# Agent Flow

AI Agent 编排与管理平台

## Prerequisites

- Python 3.12+
- Node.js 22+
- Docker & Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager)

## Quick Start

```bash
# Install all dependencies
make install

# Start development environment (Docker Compose)
make dev
```

## Project Structure

```
agent-flow/
├── backend/                 # Python (FastAPI) backend
│   ├── app/                 # Application source code
│   ├── tests/               # Backend tests
│   └── pyproject.toml       # Python dependencies (uv)
├── frontend/                # TypeScript (React) frontend
│   ├── src/                 # Frontend source code
│   └── package.json         # Node dependencies
├── deploy/                  # Deployment configurations
│   ├── docker-compose.yml
│   └── docker-compose.dev.yml
├── docs/                    # Project documentation
└── Makefile                 # Development commands
```

## Development Commands

| Command | Description |
|---|---|
| `make install` | Install all project dependencies |
| `make dev` | Start development environment |
| `make test` | Run all tests |
| `make lint` | Run linters for all packages |
| `make build` | Build Docker images |
| `make deploy` | Deploy with Docker Compose |
| `make generate-api` | Generate OpenAPI types from backend spec |

## License

MIT
