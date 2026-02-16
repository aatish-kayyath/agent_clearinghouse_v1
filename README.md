# The Agentic Clearinghouse

> **Trust Code, Not Agents.**

An escrow and verification protocol that allows AI Agents (Buyers) to hire other AI Agents (Workers) with cryptographic trust. The system holds funds, validates work via sandboxed environments or LLM judges, and releases funds only when strict criteria are met.

For full documentation (architecture, tests, loose ends, v1.1 roadmap), see [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md).

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker & Docker Compose

### 1. Setup

```bash
# Clone and enter project
cd agentic_clearinghouse

# Copy environment file
cp .env.example .env

# Install dependencies
uv sync --all-extras

# Start infrastructure (PostgreSQL + Redis)
docker compose up -d
```

### 2. Run the Server

```bash
uv run uvicorn agentic_clearinghouse.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Explore

- **REST API docs**: http://localhost:8000/docs
- **Health check**: http://localhost:8000/health
- **MCP endpoint**: http://localhost:8000/mcp

## Architecture

```
API Layer (FastAPI + MCP)
    |
Service Layer (escrow, verification, settlement)
    |
Domain Layer (state machine guards, verifier protocol, enums)
    |
Infrastructure (PostgreSQL, Redis, E2B, LiteLLM, AgentKit)
```

### State Machine

```
CREATED -> FUNDED -> IN_PROGRESS -> SUBMITTED -> VERIFYING -> COMPLETED
                                                     |
                                                     v
                                              IN_PROGRESS (retry)
                                                     |
                                                     v
                                                  FAILED (max retries)
```

### Verification Strategies

- **CodeExecutionVerifier**: Runs code in E2B sandbox, checks exit code + stdout
- **SemanticVerifier**: LLM judge via LiteLLM (GPT-4o / Llama 3)
- **SchemaVerifier**: JSON Schema validation via Pydantic

## Tests

```bash
uv run pytest tests/ -v
```

## Project Structure

```
src/agentic_clearinghouse/
├── domain/           # Pure business logic (no framework imports)
├── infrastructure/   # Database, Redis, external service adapters
├── services/         # Application use cases
├── verifiers/        # Verification strategy implementations
├── orchestration/    # LangGraph state machine workflow
├── api/              # FastAPI routes and middleware
├── mcp_server/       # MCP tool definitions
└── schemas/          # Pydantic request/response models
```

## License

MIT
