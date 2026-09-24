# IrtrixAI — Coding Assistant

IrtrixAI is a security-first AI coding assistant that helps a user understand a software workspace, plan a change, propose a patch, obtain explicit human approval, apply the approved change, run tests in an isolated Docker sandbox, repair failures within a bounded loop, review the result, and return a final task status.

The project is designed around a simple rule:

> **The model proposes. The backend validates. The human approves. The sandbox executes.**

The current README documents the frozen implementation baseline at **`e63d127049278039df42eaf1d14aeb1dd2612bcd`**. The README update itself is documentation-only; it does not change the implementation baseline.

## Project Overview

IrtrixAI combines an AI agent workflow with a real development workspace and a controlled execution environment.

The system provides:

- AI-assisted planning and code-change proposals
- Repository and workspace context gathering
- Human approval before agent-driven code mutation
- Safe file and Git operations
- Validated patch application
- Docker-based test and command execution
- A bounded repair loop
- Server-side reviewer and finalization checks
- PostgreSQL task state and LangGraph checkpoint persistence
- A React + TypeScript frontend with Monaco editor
- An embedded sandbox terminal
- FastAPI APIs and checkpoint-backed SSE task events

## Core Design Principles

### Backend authority

The browser is a UI layer, not a trust boundary. The backend performs validation, workspace selection, patch application, command validation, execution control, and final status decisions.

### Human-controlled code mutation

The LLM does not directly write to the workspace. It produces structured proposal data. The backend validates the proposal, the user explicitly approves it, and only then is the approved patch applied.

### Evidence-based completion

A task must not be marked successful only because an LLM says it is successful. Test success comes from the execution result, patch application produces an actual verified diff, and finalization applies deterministic checks before returning a completed result.

### Isolated execution

Tests and terminal commands run in ephemeral Docker containers with restricted privileges, networking, filesystem access, and resource limits.

### Bounded autonomy

The repair loop is limited to **3 repair attempts** and a separate task token budget prevents uncontrolled autonomous iteration.

### Persistent workflow state

Production LangGraph checkpoints are stored in PostgreSQL so interrupted approval and workflow state can be recovered across graph instances.

## Key Features

| Feature | What it provides |
|---|---|
| AI Planning | Converts a user task into a structured implementation plan |
| Repository Context | Selects bounded, relevant workspace files and excerpts |
| Human Approval | Explicit approval before agent code mutation |
| Patch Safety | Validates paths and applies only approved patches |
| Test Execution | Runs commands through the Docker sandbox |
| Repair Loop | Uses failed-test evidence to attempt bounded repairs |
| Code Review | Produces a structured review after testing |
| Safe Finalization | Prevents false completion when required evidence is missing |
| PostgreSQL Checkpointing | Preserves LangGraph state for pause/resume and recovery |
| Monaco IDE | Provides code inspection and controlled file editing |
| Sandbox Terminal | Executes approved commands without exposing a host shell |
| SSE Events | Exposes checkpoint-backed task progress and results for the frontend |

## System Architecture

The main components are:

```text
+------------------------+
| React + TypeScript UI  |
| Monaco IDE             |
| Sandbox Terminal       |
+-----------+------------+
            |
            | HTTP / SSE
            v
+------------------------+
| FastAPI Backend        |
| Validation / Authority |
+-----------+------------+
            |
      +-----+---------------------------+
      |                 |               |
      v                 v               v
+-----------+     +-----------+   +-----------+
| LangGraph |     | PostgreSQL|   | LLM       |
| Workflow  |     | State +   |   | Gateway   |
|           |     | Checkpoint|   | Providers |
+-----+-----+     +-----------+   +-----------+
      |
      +-------------------+
      |                   |
      v                   v
+-------------+     +-------------+
| Workspace   |     | Docker      |
| Files + Git |     | Sandbox     |
+-------------+     +-------------+
```

### Main responsibilities

| Component | Responsibility |
|---|---|
| React frontend | User interaction, editor, task status, approval UI, results |
| FastAPI | Trusted application boundary and API layer |
| LangGraph | Ordered agent workflow, interrupts, repair routing |
| PostgreSQL | Tasks, workspaces, runs, metadata, checkpoints |
| LLM Gateway | Provider-independent model interface |
| Workspace filesystem | Source-code and Git state |
| Docker sandbox | Restricted test and command execution |

## Agent Workflow

The workflow contains 10 main nodes:

```text
START
  |
  v
inspect_workspace
  |
  v
repository_context
  |
  v
planner
  |
  v
coder
  |
  v
approval_gate  <---- Human approval / rejection
  |
  +---- rejected + feedback ----> coder
  |
  +---- rejected/no feedback ---> finalize
  |
  +---- approved ----------------> apply_approved_patch
                                      |
                                      +-- error --> finalize
                                      |
                                      v
                                 test_runner
                                      |
                       +--------------+--------------+
                       |                             |
                    passed                         failed
                       |                             |
                       v                             v
                    reviewer                     debugger
                       |                             |
                       v                             v
                    finalize <-------------------- coder
                       |
                       v
                      END
```

### Important routing rules

- An unresolved approval reaches the native HITL interrupt.
- An approved non-empty patch is applied before tests run.
- Patch-application errors bypass test execution and go to finalization.
- Test success is checked with strict boolean semantics.
- Failed tests enter the bounded debugger/coder repair loop.
- Token and repair-count limits can terminate the loop.
- Reviewer output cannot turn a failed or unverified test into an approved result.
- Finalization refuses completion when proposed changes have no verified applied diff.

## Trust and Authority Model

IrtrixAI separates model output from executable authority.

```text
LLM output
    |
    v
Structured proposal
    |
    v
Backend validation
    |
    v
Human approval
    |
    v
Validated patch / command
    |
    +------------------+
    |                  |
    v                  v
Workspace mutation   Docker execution
    |                  |
    +--------+---------+
             |
             v
       Deterministic evidence
             |
             v
          Reviewer
             |
             v
          Finalize
```

The LLM is therefore not the authority for:

- writing arbitrary workspace files
- selecting an arbitrary host path
- executing an arbitrary host command
- declaring tests successful
- bypassing human approval
- declaring a task completed

## Human-in-the-Loop Governance

For a normal code-changing task:

1. The planner and coder produce structured outputs.
2. The proposed change is shown to the user.
3. The workflow pauses at the approval boundary.
4. The user approves or rejects the proposal.
5. Only an approved proposal can reach patch application.
6. Repair cycles re-arm approval before another mutation.
7. Finalization uses backend state and execution evidence rather than trusting the UI or LLM alone.

A legitimate no-op remains supported when the coder proposes no file changes and no patch.

## Patch and Filesystem Safety

Workspace operations are bound to registered workspace roots.

Controls include:

- Path normalization and workspace boundary checks
- Absolute-path escape prevention
- Path traversal prevention
- Symlink-aware boundary validation
- Protected-file patterns for secrets and private keys
- Explicit read/write byte limits
- Bounded search results and file sizes
- Patch size limits
- Atomic file replacement for writes
- Validation of multi-file patch targets
- Rollback handling when a multi-file patch cannot be completed safely

The workspace filesystem and Git repository remain the source of truth for source code. PostgreSQL stores application state and workflow metadata rather than becoming a second source of code truth.

## Docker Sandbox and Execution Security

Execution is performed through an ephemeral Docker sandbox.

| Control | Current setting |
|---|---|
| User | `1000:1000` non-root |
| Network | Disabled (`--network=none`) |
| Capabilities | All dropped |
| Privilege escalation | Disabled with no-new-privileges |
| Root filesystem | Read-only |
| Workspace mount | Read-only |
| CPU | 1.0 |
| Memory | 512 MB |
| PIDs | 64 |
| Temporary storage | 64 MB tmpfs |
| Temporary storage flags | `noexec,nosuid` |
| Timeout | 30 seconds |
| Output | Bounded to 50 KB |
| Docker socket inside sandbox | Not mounted |

The sandbox is intended to limit the impact of generated or user-supplied commands. It is not intended to provide a public untrusted-compute service without additional deployment isolation.

## Embedded Sandbox Terminal

The terminal is a request-response command console rather than a persistent host shell.

```text
Browser Terminal
      |
      v
FastAPI
      |
      v
Workspace lookup
      |
      v
Command policy validation
      |
      v
Docker execution service
      |
      v
Sandbox container
      |
      v
Bounded stdout / stderr / exit code
```

The browser does not execute host commands directly.

There is no persistent PTY or unrestricted host shell in the current design.

## Monaco IDE and Workspace Editing

The frontend includes a Monaco-based code editor.

The save flow uses an optimistic content hash:

```text
Read file
   |
   v
Content + SHA-256
   |
   v
Edit in Monaco
   |
   v
PUT file + expected hash
   |
   +-- current hash differs --> 409 conflict
   |
   +-- hash matches ---------> atomic save
```

The hash protects against silently overwriting a newer version detected before the save.

## Database, Checkpointing and State

PostgreSQL stores application and workflow state such as:

- Workspaces
- Tasks
- Execution runs
- Task status
- Provider/model information
- Repair counters and runtime metrics
- LangGraph checkpoints
- Operational metadata

Production checkpointing is configured with an explicit `JsonPlusSerializer` allowlist for the agent contract types stored in checkpoints.

The production checkpointer is PostgreSQL-backed and is designed to fail closed when the required database-backed checkpointer is unavailable.

## Task Lifecycle and Concurrency

The backend uses PostgreSQL-backed task and workspace state to coordinate execution.

The design includes:

- Task-level locking
- Workspace-level locking
- Protection against conflicting concurrent runs
- Approval reservation and state checks
- Terminal-state protection
- Stale task reconciliation
- Cancellation handling
- Multi-worker concurrency tests

The goal is to prevent two workers or tasks from incorrectly operating on the same workspace at the same time.

## API Surface

### Task APIs

```text
POST /api/v1/tasks
GET  /api/v1/tasks/{task_id}
POST /api/v1/tasks/{task_id}/run
POST /api/v1/tasks/{task_id}/approval
POST /api/v1/tasks/{task_id}/cancel
GET  /api/v1/tasks/{task_id}/events
GET  /api/v1/tasks/analytics
```

### Workspace APIs

```text
GET  /api/v1/workspaces
POST /api/v1/workspaces
GET  /api/v1/workspaces/{workspace_id}/tree
GET  /api/v1/workspaces/{workspace_id}/files/{file_path}
PUT  /api/v1/workspaces/{workspace_id}/files/{file_path}
POST /api/v1/workspaces/{workspace_id}/terminal/execute
```

### SSE behavior

`GET /events` is an observation endpoint. It reads checkpoint-backed task state and emits the corresponding task events; it does not start or advance an unstarted task.

Task execution is explicitly started with:

```text
POST /api/v1/tasks/{task_id}/run
```

## LLM Gateway

The application keeps provider-specific logic behind a common LLM gateway.

The configuration supports:

- Ollama for local model execution
- Gemini
- Groq
- Structured Pydantic contracts for planner, coder, debugger, reviewer, and finalization data

Model output is treated as untrusted proposal data until deterministic backend checks accept it.

## Failure Handling and Recovery

The workflow is designed to fail safely rather than silently report success.

| Failure | Expected behavior |
|---|---|
| LLM error | Preserve failure state and stop/return safely |
| Approval rejection | End or re-enter coding only with explicit feedback |
| Patch failure | Do not run tests on an unapplied patch; finalize as failed |
| Test failure | Enter bounded repair flow |
| Too many repairs | Stop and finalize |
| Token budget reached | Stop and finalize |
| Reviewer approval conflicts with failed tests | Server-side rejection |
| Process/workflow interruption | Recover state from PostgreSQL checkpoint |
| Task cancellation | Preserve terminal cancellation state |

## Security Boundaries

The main security boundaries are:

1. **Browser → Backend**: the browser is not trusted with host-level authority.
2. **LLM → Backend**: model output is untrusted data.
3. **Backend → Workspace**: paths are validated against registered workspace roots.
4. **Backend → Docker**: commands are validated and executed in constrained containers.
5. **Execution → Finalization**: completion depends on deterministic execution evidence.
6. **Application → PostgreSQL**: task and checkpoint state support recovery and concurrency control.

## Testing and Verification

The project uses multiple test layers.

| Test layer | Purpose |
|---|---|
| Fast unit tests | State rules, routing, contracts, validation and security helpers |
| PostgreSQL integration | Checkpoint persistence, task state, APIs and concurrency |
| Docker security tests | Real sandbox limits and execution boundary |
| Multi-worker tests | Concurrent worker/task behavior |
| Filesystem / workflow tests | Actual patch, workspace and graph behavior |
| Frontend build | TypeScript validation and production bundle generation |
| CLI tests | Command-line client behavior |

### Latest verified baseline

The frozen implementation baseline is:

```text
e63d127049278039df42eaf1d14aeb1dd2612bcd
```

Local verification reported:

```text
363 passed
8 skipped
```

GitHub Actions run **#45** for this baseline completed successfully across:

- Job A — Fast Unit Tests & Install Gate
- Job B — PostgreSQL 16 Concurrency & Checkpointing
- Job C — Real Docker Sandbox Security Tests
- Job D — Security Gate & Multi-Worker Validation

Ruff and the CI quality gates also passed in that run.

## Getting Started

### Prerequisites

- Docker Desktop or Docker Engine
- Docker Compose
- Python 3.12+
- Node.js 20+

### Start the application

Copy the example environment file:

```bash
cp .env.example .env
```

Review provider, database, and workspace settings before starting.

Then:

```bash
docker compose up --build -d
```

Local endpoints:

```text
Frontend:       http://localhost:5173
Backend health: http://localhost:8000/health
OpenAPI docs:   http://localhost:8000/docs
```

### Backend development

```bash
cd backend
python -m pip install -e ".[dev]"
python -m pytest tests -v
ruff check .
```

### Frontend development

```bash
cd frontend
npm install
npm run dev
```

Production build:

```bash
npm run build
```

### Testing infrastructure

The repository also contains a dedicated PostgreSQL test Compose configuration:

```bash
docker compose -f docker-compose.test.yml up -d
```

Use the test configuration when running tests that require external PostgreSQL infrastructure.

## Project Structure

```text
irtrixai-coding-assistant/
├── .env.example
├── .github/
│   └── workflows/
│       └── ci.yml
├── README.md
├── docker-compose.yml
├── docker-compose.test.yml
├── docker/
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   └── sandbox.Dockerfile
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── agent/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── tools/
│   └── tests/
├── cli/
│   ├── pyproject.toml
│   ├── src/
│   └── tests/
└── frontend/
    ├── package.json
    ├── package-lock.json
    └── src/
        ├── components/
        └── services/
```

## Deployment Model and Boundaries

### Supported target

The current architecture is intended for:

- Local development
- A private internal environment
- A trusted single-tenant deployment
- Controlled workspaces registered by trusted operators

### Not currently supported

The current MVP is not intended to be an internet-facing, public multi-tenant code-execution service.

The following are outside the current security scope:

- Authentication
- RBAC
- Multi-user tenancy
- Public untrusted execution
- Kubernetes-based execution isolation
- Remote Git push / pull-request automation
- WebSocket terminal sessions
- Vector database / embedding infrastructure

### Docker daemon access

The Docker Compose backend mounts the host Docker socket because the backend manages sandbox containers.

This is acceptable for the current trusted local/private model, but it means the backend itself has powerful Docker-daemon access. A future public or multi-tenant deployment should use a more isolated Docker control-plane design before accepting untrusted users.

## Current Configuration Limits

| Setting | Value |
|---|---:|
| Max workspace depth | 5 |
| Max readable file size | 1 MB |
| Max writable file size | 1 MB |
| Max tool/command output | 50 KB |
| Max search results | 100 |
| Max search file size | 500 KB |
| Max patch size | 256 KB |
| Command timeout | 30 s |
| Sandbox timeout | 30 s |
| Sandbox memory | 512 MB |
| Sandbox CPU | 1.0 |
| Sandbox PIDs | 64 |
| Sandbox tmpfs | 64 MB |
| Max repair attempts | 3 |
| Max task token budget | 35,000 |

## Future Development

Future work can extend the platform without changing the current security boundaries.

### Security and operations

- Authentication and RBAC
- Rate limiting and abuse controls
- Stronger secret management
- Audit trails
- Stronger concurrent-save guarantees
- Centralized monitoring and alerting
- Safer Docker control-plane isolation for public deployments

### Developer experience

- Better file picker
- Editor navigation and tabs
- Richer terminal interaction
- Additional workspace tooling

### AI capabilities

- Better repository context selection
- Stronger planning and repair quality
- Task benchmarks and evaluation sets
- Improved model routing

### Platform capabilities

- Multi-user workspaces
- Remote Git operations
- Pull-request workflows
- Optional LSP integration
- Collaboration features

## Documentation Notes

For architecture and design details, see the technical documentation accompanying the project.

The implementation source remains the final authority for behavior. Documentation should be updated whenever a user-visible API, security boundary, workflow rule, or deployment model changes.
