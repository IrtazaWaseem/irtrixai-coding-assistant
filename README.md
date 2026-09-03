# IrtrixAI — Coding Assistant

A security-first, deterministic AI coding assistant built on a layered architecture featuring sandboxed execution, Human-in-the-Loop (HITL) approval gates, and strict filesystem isolation.

## Key Architectural Principles

- **Deterministic Execution Layer**: System commands and Docker invocations are deterministically mapped and validated through backend dispatchers rather than executing raw, unvalidated model output strings.

- **Filesystem Security Boundary**: All file accesses are resolved through `resolve_safe_path` to strictly prevent path traversal (`../`), host root escapes, and symlink hijacking.

- **Human-in-the-Loop Governance**: Every code patch stops at a structured diff review screen. Changes require explicit user approval before mutating the working tree.

- **Isolated Sandboxing**: Execution runs in ephemeral, non-root containers with complete network isolation (`network=none`) and constrained memory/CPU quotas.

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (asyncio), asyncpg, Alembic, Pydantic v2, Ruff, Pytest
- **Persistence**: PostgreSQL 16 Alpine
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS
- **Orchestration**: Docker Compose

## Project Structure

```text
irtrixai-coding-assistant/
├── docker-compose.yml
├── docker/
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   └── sandbox.Dockerfile
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   └── ...
│   ├── app/
│   │   ├── api/v1/
│   │   ├── core/
│   │   ├── db/
│   │   ├── schemas/
│   │   └── services/
│   └── tests/
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.ts
    └── src/
```

## Getting Started

### Prerequisites

- Docker Desktop / Docker Engine
- Docker Compose
- Python 3.12+ for local host development
- Node.js 20+ for local host development

### 1. Environment Setup

Copy the example environment configuration:

```bash
cp .env.example .env
```

### 2. Start Services via Docker Compose

Run all services in detached mode:

```bash
docker compose up --build -d
```

Verify service availability:

- Frontend: http://localhost:5173
- Backend Health Check: http://localhost:8000/health
- Interactive OpenAPI Documentation: http://localhost:8000/docs

## Development & Testing

### Local Backend Setup

```bash
cd backend

conda activate irtrixai
# or activate your virtual environment

pip install -e ".[dev]"
```

### Run Tests

Execute the complete backend test suite, including unit, integration, and symlink security tests:

```bash
python -m pytest backend/tests -v
```

### Code Quality & Linting

Run Ruff from the backend directory:

```bash
cd backend
ruff check .
```

### Build Frontend

Verify TypeScript compilation and the production client bundle:

```bash
cd frontend
npm run build
```

## 15-Day Implementation Roadmap

### Day 1 — Scaffolding, Persistence & Security Baseline

- [x] Project monorepo scaffolding (FastAPI + React + PostgreSQL)
- [x] Async SQLAlchemy 2.0 schema and Alembic migrations
- [x] Filesystem traversal security guard (`resolve_safe_path`)
- [x] Multi-container Docker Compose environment

### Day 2 — Safe File Tools & Git Engine

- [ ] Safe file tools
- [ ] Git inspection and diff tools
- [ ] Tool contracts and validation

### Day 3 — Ephemeral Docker Sandbox Execution

- [ ] Isolated Docker execution
- [ ] Command allowlisting
- [ ] Resource and timeout limits

### Day 4 — LLM Gateway & Structured Output Schemas

- [ ] Unified LLM provider abstraction
- [ ] Structured model outputs
- [ ] Provider configuration

### Day 5 — LangGraph Architecture

- [ ] Workspace inspection
- [ ] Planning
- [ ] Code generation
- [ ] LangGraph state and graph structure

### Day 6 — Approval Gates & Test-Repair Loop

- [ ] Human approval interrupt
- [ ] Test execution
- [ ] Debugger loop
- [ ] Maximum repair limit

### Day 7 — FastAPI Agent Orchestration APIs

- [ ] Task creation
- [ ] Run management
- [ ] Approval and cancellation endpoints
- [ ] LangGraph checkpointer integration

### Day 8 — Server-Sent Events (SSE) Streaming

- [ ] Agent event streaming
- [ ] Tool execution events
- [ ] Test output streaming
- [ ] Event replay support

### Day 9 — React Architecture & State Management

- [ ] React application architecture
- [ ] Zustand stores
- [ ] API client
- [ ] SSE client

### Day 10 — Monaco Editor & File Explorer

- [ ] Monaco Editor
- [ ] File tree
- [ ] Multi-file tabs
- [ ] Diff viewer

### Day 11 — Terminal Stream & Plan Checklist UI

- [ ] xterm.js log viewer
- [ ] Real-time agent output
- [ ] Plan checklist
- [ ] Task status visualization

### Day 12 — End-to-End Human-in-the-Loop Workflow

- [ ] Agent-generated patch
- [ ] Diff review
- [ ] User approval
- [ ] Rejection and revision flow

### Day 13 — Edge Case & Security Hardening

- [ ] Security boundary testing
- [ ] Tool failure handling
- [ ] Repair-loop limits
- [ ] Patch failure recovery

### Day 14 — Local Models & Prompt Injection Defenses

- [ ] Ollama integration
- [ ] Local model validation
- [ ] Prompt injection testing
- [ ] Untrusted workspace content isolation

### Day 15 — Final Polish, Benchmarking & Demo

- [ ] End-to-end testing
- [ ] Performance verification
- [ ] Security verification
- [ ] UI polish
- [ ] Demo scenarios
- [ ] Final architecture verification

## Current Status

**Day 1: COMPLETE**

The foundation is implemented and verified. The next milestone is **Day 2: Safe File Tools & Git Engine**.
