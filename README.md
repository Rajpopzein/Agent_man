# Agent Man

Agent Man is a Windows-first desktop environment for creating and running role-based AI agents inside project sandboxes.

## Product principles

- A project owns the sandbox and shared execution environment.
- Each agent owns its role, model/provider configuration, tools, MCP access, memory, and self-building policy.
- A project may run one agent or multiple peer agents.
- Agents can use controlled filesystem, terminal, process, port, device and MCP capabilities.
- Agents may create and improve tools through a versioned validation pipeline.
- The trusted runtime, permission engine, secrets manager, sandbox broker, updater and audit log cannot be modified by ordinary agent self-building.
- A local-model agent must never silently fall back to a cloud model with private project context.

## Repository

- `apps/web` — React desktop UI
- `apps/desktop` — reserved for the Tauri Windows host
- `runtime` — Python/FastAPI agent runtime
- `packages` — shared contracts when required
- `docs` — architecture and product specifications
- `scripts` — development/automation entry points

The repository layout is governed by [docs/FOLDER_STRUCTURE.md](docs/FOLDER_STRUCTURE.md).

## Planned stack

- Windows desktop: Tauri
- UI: React + TypeScript + Vite + MUI
- Runtime/API: Python + FastAPI
- Realtime: WebSocket
- Persistence: SQLite + SQLAlchemy
- LLMs: per-agent provider adapters for local and cloud providers
- Integrations: MCP client/gateway

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/UI_SPEC.md](docs/UI_SPEC.md), and [docs/ROADMAP.md](docs/ROADMAP.md).
