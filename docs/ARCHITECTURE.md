# Agent Man Architecture

## Product hierarchy

```text
User
└── Project
    ├── Sandbox
    ├── Shared task context
    ├── Processes / ports / approved devices
    ├── Project MCP permissions
    └── Agents
        ├── Role
        ├── Individual LLM configuration
        ├── Tools
        ├── MCP connections
        ├── Permissions
        ├── Memory
        └── Self-building policy
```

## Trusted core

The following components are outside normal agent modification:

- Agent Runtime
- Permission Engine
- Sandbox Broker
- Secrets Manager
- Device Broker
- Tool Validator
- Audit/Event Log
- Application Updater

## Agent model

An agent is a runtime worker instance. A role defines behavior. Tools define executable capabilities.

Each agent independently selects:

- provider connection
- model
- context policy
- generation parameters
- fallback policy

This permits, for example, an Architect using Gemini, a Developer using LM Studio, and a Tester using another local model in the same project.

Cloud fallback requires explicit permission before local/private context crosses the local-to-cloud boundary.

## Execution

```text
CREATED -> ANALYZING -> PLANNED -> EXECUTING -> VALIDATING -> COMPLETED
                                  |             |
                                  v             v
                           WAITING_APPROVAL   REPLAN
```

Completion is runtime-validated, not declared solely by an LLM.

## Sandbox capabilities

Initial brokered capabilities:

- workspace filesystem
- terminal commands
- process lifecycle
- local port allocation and inspection
- stdout/stderr streaming
- Git operations
- serial/COM discovery and access

Later capability families may include USB, Bluetooth, GPU, camera, microphone and network-interface access.

## MCP

MCP is a first-class connection layer. Users can configure local/stdio or remote MCP servers, discover exposed tools/resources/prompts, and grant MCP access per project and per agent. Credentials remain in the secrets layer and are not injected into model context.

## Self-building

Agents can detect missing capabilities and propose new or improved tools.

```text
missing capability
  -> draft tool
  -> manifest + implementation + tests
  -> sandbox execution
  -> permission/security validation
  -> approval when required
  -> versioned activation
```

An active tool is never overwritten in-place. New revisions are staged and rollback remains possible.
