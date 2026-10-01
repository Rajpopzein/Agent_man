# Agent configuration and background activity

In **Settings → Configure agents**, select a project agent to edit its name,
role, instructions, AI connection, or model. Use **Add agent** to create one.

Executive can also inspect and update these settings through chat. For example:

- “Show the Developer agent’s configuration.”
- “Change the Tester’s model to [model identifier] using [connection name].”
- “Update the Reviewer’s instructions to focus on regression tests.”

Executive can discover available connection names and IDs without reading API
keys. Changes are limited to agents in the selected project and preserve fields
that were not requested. Configuration changes affect subsequent runs; they do
not restart work already in progress. Tool assignments remain managed on the
Tools page.

Open **Background** in the navigation to monitor:

- Agent jobs: status, current action and tool, step count, update time, task,
  result, and errors. Filter to active jobs or an individual status.
- Managed processes in the project's workspace: command, PID, port, exit code,
  and latest output. Select a process to follow its output.

The page refreshes every two seconds and shows connection failures while retaining
the last received data. Job and process history is held in memory for the current
runtime session. Processes launched outside Agent Man are not included.

Restart the runtime after upgrading to load Executive's new configuration actions
and project-scoped process endpoints.
