# Agent Man UI Specification

## Visual direction

A professional dark command-center interface inspired by futuristic AI/HUD systems without copying a specific fictional UI. Visual effects must represent real runtime state rather than decoration.

## Desktop shell

Primary navigation:

- Dashboard
- Projects
- Agents
- Chat
- MCP Connections
- Tools
- Sandbox
- Devices & Ports
- Activity
- Settings

The shell includes a global agent/task command bar, system health indicator, current project switcher and approval notifications.

## Dashboard

### Top metrics

- Active Agents
- Running Tasks
- Tools Available
- MCP Connections
- Sandbox Health

### Agent Network

Central project node with surrounding active agents. Edges animate only during real communication/tool handoff. Each agent displays role, provider/model, status and current operation.

### Agent Status

Compact cards for every active agent with:

- role/name
- provider/model
- state: idle, thinking, waiting, executing, validating, failed
- current task
- quick inspect action

### Workspace

Tabbed panel:

- Chat
- Planner
- Artifacts
- Code
- Preview

Chat supports targeting one agent, selected agents, or the project team.

### Live Activity

Chronological event stream covering agent messages, tool calls, file modifications, MCP calls, process lifecycle, port allocation, approvals, tests and errors.

### Sandbox & Resources

Tabs:

- Ports
- Processes
- Devices

Ports show owner agent/process and lifecycle state. Devices show detected COM/device identity and access policy.

### MCP panel

Shows configured MCP connections, health, discovered tool count, assigned agents and enable/disable controls.

## Create/Edit Agent

Fields:

- Name
- Role
- Description
- Provider connection
- Model
- Context policy
- Model parameters
- Tools
- MCP connections
- Filesystem/terminal/network/port/device permissions
- Memory policy
- Self-building permissions
- Fallback models

Provider/model configuration is individual to the agent, never forced project-wide.

## Project screen

Displays project workspace path, agents, shared context, active tasks, sandbox resources, MCP permissions, artifacts and project-level security policy.

## Approval UX

High-risk operations use an explicit approval surface showing:

- requesting agent
- exact operation
- affected resource
- reason
- risk
- allow once / project policy / deny

Cloud fallback additionally identifies what project context would leave the local machine.
