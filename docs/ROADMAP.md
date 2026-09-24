# Agent Man Roadmap

## Phase 1 — Windows foundation

- Tauri + React desktop shell
- FastAPI runtime process
- SQLite persistence
- project CRUD
- agent CRUD
- per-agent provider/model configuration
- dashboard shell
- event stream
- filesystem sandbox
- terminal broker
- process and port manager
- permission/approval foundation

Exit criteria: one configured agent can work inside one project sandbox, run a controlled development task, expose a local process, and produce an auditable event trail.

## Phase 2 — Reliable agent runtime

- role definitions
- tool registry
- provider adapters
- context-window management
- secrets store
- task state machine
- validation/acceptance criteria
- memory boundaries

Exit criteria: task completion is validated and model/context failures are recoverable.

## Phase 3 — Multi-agent

- peer-agent messaging
- shared task context
- role assignment
- concurrent work
- conflict handling
- agent-network visualization

Exit criteria: multiple agents using different providers can collaborate on one project without a permanent coordinator agent.

## Phase 4 — MCP

- stdio MCP
- remote MCP
- discovery
- per-agent grants
- connection health
- secrets integration
- GitHub MCP workflow
- custom MCP UI

## Phase 5 — Windows devices

- COM discovery
- serial broker
- device approval
- resource ownership
- ESP32-oriented workflow
- later: controlled USB/Bluetooth/GPU/media-device capabilities

## Phase 6 — Self-building

- capability-gap detection
- tool builder
- manifests
- generated tests
- sandbox validation
- permission analysis
- versioning
- rollback
- repair loop

## Phase 7 — Self-development

- isolated Agent Man development workspace
- branch-based modifications
- build/test validation
- update proposal
- controlled application updater

Agents never directly replace the running trusted core.
