# Folder Structure Contract

This structure is an architectural contract. New code must be placed in its owning module; convenience files must not accumulate at repository root.

```text
Agent_man/
├── .github/workflows/
├── apps/
│   ├── desktop/                 # Tauri Windows host
│   └── web/                     # React UI
│       └── src/
│           ├── app/
│           ├── components/
│           ├── features/
│           │   ├── dashboard/
│           │   ├── projects/
│           │   ├── agents/
│           │   ├── chat/
│           │   ├── sandbox/
│           │   ├── tools/
│           │   ├── mcp/
│           │   ├── devices/
│           │   └── settings/
│           ├── services/
│           ├── hooks/
│           ├── types/
│           └── styles/
├── runtime/                     # Python Agent Man runtime
│   ├── app/
│   │   ├── api/
│   │   ├── core/                # trusted runtime core
│   │   ├── domain/              # domain entities
│   │   ├── persistence/
│   │   ├── agents/
│   │   ├── providers/
│   │   ├── sandbox/
│   │   ├── tools/
│   │   ├── mcp/
│   │   ├── devices/
│   │   └── events/
│   └── tests/
├── packages/                    # shared schemas/contracts when needed
├── docs/
├── scripts/
└── README.md
```

## Rules

1. `runtime/app/core` is trusted-core code and is never a destination for agent-generated tools.
2. Provider-specific logic stays under `runtime/app/providers`.
3. MCP implementation stays under `runtime/app/mcp`; MCP-backed product features do not leak provider logic into agents.
4. Sandbox OS access stays under `runtime/app/sandbox` and `runtime/app/devices`.
5. User/self-built tools are represented by the tool registry and stored in sandbox/application data, not committed into trusted runtime directories during normal operation.
6. UI business features live in `apps/web/src/features/<feature>`; reusable visual primitives live in `components`.
7. Cross-layer contracts belong in `packages` only when actually shared; do not create premature abstractions.
