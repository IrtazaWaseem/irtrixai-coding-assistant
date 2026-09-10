# IrtrixAI — Coding Assistant

A security-first, deterministic AI coding assistant built on a layered architecture featuring sandboxed execution, Human-in-the-Loop (HITL) approval gates, strict filesystem isolation, LangGraph orchestration, PostgreSQL checkpointing, and a React frontend with SSE-based task streaming.

## Key Architectural Principles

- **Deterministic Execution Layer**: System commands and Docker invocations are deterministically mapped and validated through backend dispatchers rather than executing raw, unvalidated model output strings.
- **Filesystem Security Boundary**: All file accesses are resolved through `resolve_safe_path` and explicit workspace roots to prevent path traversal (`../`), host-root escapes, and symlink hijacking.
- **Human-in-the-Loop Governance**: Every code proposal pauses at a structured approval gate. Changes require explicit user approval before mutating the working tree.
- **Isolated Sandboxing**: Execution runs in ephemeral, non-root containers with network isolation (`network=none`) and constrained CPU, memory, PID, timeout, and temporary-storage limits.
- **Checkpointed Agent State**: LangGraph state is persisted with PostgreSQL in production so interrupted workflows can safely resume from the same task/thread.
- **Observation-Only Streaming**: `GET /events` is an observation endpoint. Task execution is explicitly triggered by `POST /run`; connecting to SSE never starts an unstarted task.
- **Backend Authority**: The frontend only collects input, observes events, displays proposals/results, and submits human decisions. Validation, patch application, sandbox execution, and authorization remain backend responsibilities.

## Current Capabilities

- Secure filesystem and Git inspection tools
- Workspace-bound patch validation and application
- Docker sandbox execution with command allowlisting and resource controls
- Unified LLM gateway with local/cloud provider support
- Structured Pydantic model contracts for planner, coder, debugger, reviewer, and finalization stages
- LangGraph agent workflow with native HITL interrupts
- PostgreSQL-backed LangGraph checkpointing
- Bounded test/repair loop with a maximum of 3 repair attempts
- FastAPI task, run, approval, and SSE endpoints
- React + TypeScript frontend for task creation, live progress, approval, diffs, test results, review results, and final status

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, Pydantic v2, Ruff, Pytest
- **Persistence**: PostgreSQL 16 Alpine
- **Agent orchestration**: LangGraph
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS
- **Execution**: Docker / Docker Compose

## Project Structure

```text
irtrixai-coding-assistant/
├── .env.example
├── .gitignore
├── README.md
├── docker-compose.yml
├── docker/
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   └── sandbox.Dockerfile
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       └── 0001_create_initial_schema.py
│   ├── app/
│   │   ├── agent/
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── core/
│   │   ├── db/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── tools/
│   ├── scripts/
│   └── tests/
└── frontend/
    ├── index.html
    ├── package.json
    ├── package-lock.json
    ├── postcss.config.js
    ├── tailwind.config.js
    ├── tsconfig.json
    ├── tsconfig.node.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx
        ├── index.css
        ├── main.tsx
        ├── types.ts
        ├── vite-env.d.ts
        ├── components/
        └── services/
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

Review the provider/checkpoint settings in `.env` before starting the application.

### 2. Start Services via Docker Compose

Run the application stack:

```bash
docker compose up --build -d
```

Verify service availability:

- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8000/health`
- Interactive OpenAPI documentation: `http://localhost:8000/docs`

> The Vite development server uses its configured local port during host development; the Dockerized frontend uses the port exposed by the Compose configuration.

## API Surface

The current task-control API includes:

```text
POST /api/v1/tasks
GET  /api/v1/tasks/{task_id}
POST /api/v1/tasks/{task_id}/run
POST /api/v1/tasks/{task_id}/approval
GET  /api/v1/tasks/{task_id}/events
```

The execution lifecycle is:

```text
POST /tasks
     ↓
POST /tasks/{id}/run
     ↓
inspect_workspace
     ↓
planner
     ↓
coder
     ↓
HITL approval interrupt
     ↓
approved patch application
     ↓
Docker sandbox test
     ↓
reviewer
     ↓
finalize
```

On test failure, the bounded repair loop routes through debugger → coder → HITL → patch → test, with a maximum of three repair attempts.

`GET /events` only observes/replays checkpoint-backed execution state. It does not initialize or advance an unstarted graph.

## Development & Testing

### Local Backend Setup

```bash
cd backend

# Use your existing Conda environment or another virtual environment
conda activate irtrixai

pip install -e ".[dev]"
```

### Run Backend Tests

From the repository root:

```bash
python -m pytest backend/tests -v
```

Or from `backend/`:

```bash
python -m pytest tests -v
```

### Code Quality & Linting

From `backend/`:

```bash
ruff check .
```

### Build Frontend

From `frontend/`:

```bash
npm install
npm run build
```

## Security Model

IrtrixAI is intentionally designed so that the model is **not** the final authority over system actions.

```text
LLM output
   ↓
structured proposal
   ↓
application validation
   ↓
Human approval
   ↓
validated patch/tool action
   ↓
isolated execution
```

Important boundaries include:

- Workspace paths are resolved and checked before filesystem access.
- Protected files and traversal/symlink escape attempts are rejected.
- Command execution is allowlisted and sandboxed.
- The sandbox is non-root, network-isolated, resource-constrained, and does not receive the Docker socket.
- Approval is checkpoint/state-driven rather than trusted from frontend UI state.
- Repair cycles are bounded to prevent uncontrolled autonomous iteration.
- Production LangGraph checkpointing uses PostgreSQL rather than silently falling back to an in-memory saver.

Authentication/RBAC, multi-user tenancy, remote Git push/PR creation, Kubernetes, WebSockets, vector RAG, and other larger platform features remain intentionally outside the current MVP scope.

## 15-Day Implementation Roadmap

### Day 1 — Foundation, Persistence & Security Baseline

- Project monorepo scaffolding
- Async SQLAlchemy schema and Alembic migration
- Filesystem security baseline
- Docker Compose foundation

### Day 2 — Safe File Tools & Git Engine

- Secure file tools
- Git status/diff tooling
- Uniform tool contracts and validation
- Workspace and symlink security hardening

### Day 3 — Ephemeral Docker Sandbox

- Isolated Docker execution
- Command allowlisting
- Resource and timeout limits
- Non-root, network-isolated execution

### Day 4 — LLM Gateway & Structured Outputs

- Unified provider gateway
- Ollama / cloud-provider architecture
- Structured Pydantic outputs
- Provider fallback and error handling

### Day 5 — LangGraph Agent Architecture

- Agent state
- Workspace inspection
- Planning
- Coding proposals
- HITL interrupt/resume
- PostgreSQL checkpointing
- Patch application and repair-loop foundations

### Day 6 — Task APIs, Execution Control & SSE Backend

- Task creation and retrieval
- Graph execution endpoint
- HITL approval endpoint
- SSE event streaming
- Task/thread isolation

### Day 6.5 — Concurrency & Status Hardening

- Observation-only `/events`
- PostgreSQL row-level locking for task execution/approval
- Task/checkpoint status reconciliation
- Graph/checkpointer error containment

### Day 7 — Real Agent Tool Execution

- Authoritative filesystem/Git tool integration
- Real `execute_in_sandbox()` integration
- ToolResult normalization
- End-to-end workflow verification
- Three-repair governance verification

### Day 7.5 — Post-Audit Hardening

- Concurrent approval protection
- Safe graph error handling
- Final SSE event naming cleanup
- Lint/regression cleanup

### Day 8 — React Frontend & HITL Dashboard

- React + TypeScript application
- Task creation UI
- Live SSE activity timeline
- Approval and rejection controls
- Read-only diff viewer
- Test/review/final result panels
- Safe refresh/reconnect behavior

### Day 9 — Repository Intelligence & Context

- Deterministic repository context gathering
- Relevant file discovery using existing tools
- Bounded context assembly
- Better context passed to planner/coder
- No vector database required for this milestone

### Day 10 — Planner/Coder Quality

- Improve plan quality
- Improve relevant-file selection
- Prefer minimal patches
- Improve test generation
- Improve debugger/coder repair reasoning
- Preserve structured contracts and security boundaries

### Day 11 — Reliability, Concurrency & Recovery

- Execution concurrency hardening
- Checkpoint recovery
- Crash/status reconciliation
- SSE recovery behavior
- Idempotency and state-transition testing

### Day 12 — Adversarial Security Hardening

- Path traversal testing
- Symlink escape testing
- Command-injection testing
- Malicious patch testing
- Protected-file testing
- Prompt-injection testing
- Cross-task isolation testing
- Sandbox boundary testing

### Day 13 — Git Intelligence

- Git log/history context
- Blame information where useful
- Branch inspection
- Additive Git tools returning standard ToolResult

### Day 14 — Production Polish & Observability

- Structured logging
- Event/history persistence where justified
- Deployment polish
- Configuration cleanup
- UX polish
- Operational documentation

### Day 15 — Final Audit, Benchmarking & Demo

- Full regression suite
- Security re-verification
- Performance checks
- Architecture verification
- Documentation completion
- Demo scenarios
- Final release readiness review

## Current Status

**Day 8: COMPLETE / AUDITED**

The current MVP foundation, secure execution workflow, task API, checkpointing, SSE backend, and first React frontend are implemented and independently reviewed. The next milestone is **Day 9: Repository Intelligence & Context**.

Latest verified frontend baseline:

- React 18 + TypeScript + Vite + Tailwind
- Task creation and execution controls
- SSE observation client
- HITL approval/rejection UI
- Diff rendering
- Test/review/final result views

The project deliberately prioritizes security, deterministic boundaries, and verifiable behavior over prematurely adding multi-user SaaS infrastructure or large AI platform features.
