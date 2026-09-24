from dataclasses import dataclass
from typing import Any

from app.core.permissions import Permission, require
from app.sandbox.filesystem import ProjectFilesystem
from app.sandbox.managed_processes import processes
from app.sandbox.ports import ports
from app.sandbox.processes import ProjectProcessRunner


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    risk: str
    arguments: dict[str, str]


TOOL_DEFINITIONS = [
    ToolDefinition("list_files", "List files and folders inside the project.", "read", {"path": "relative directory path"}),
    ToolDefinition("read_file", "Read a UTF-8 text file inside the project.", "read", {"path": "relative file path"}),
    ToolDefinition("write_file", "Create or replace a UTF-8 text file inside the project.", "write", {"path": "relative file path", "content": "complete file content"}),
    ToolDefinition("run_command", "Run a shell command and wait for completion.", "execute", {"command": "shell command"}),
    ToolDefinition("check_port", "Check whether a local TCP port is free.", "read", {"port": "port number"}),
    ToolDefinition("allocate_port", "Reserve a free local TCP port for this runtime.", "write", {"start": "first port", "end": "last port"}),
    ToolDefinition("list_processes", "List background processes started by Agent Man.", "read", {}),
    ToolDefinition("start_process", "Start a background process in the project workspace.", "execute", {"command": "shell command", "port": "optional port to reserve"}),
    ToolDefinition("read_process_output", "Read recent output from a managed process.", "read", {"process_id": "managed process id"}),
    ToolDefinition("stop_process", "Stop a managed background process.", "execute", {"process_id": "managed process id"}),
]


def catalog_for_prompt() -> str:
    lines = []
    for tool in TOOL_DEFINITIONS:
        args = ", ".join(f"{key}: {value}" for key, value in tool.arguments.items())
        lines.append(f"- {tool.name} [{tool.risk}]: {tool.description} Args: {args}")
    return "\n".join(lines)


class ToolRegistry:
    def execute(self, *, name: str, arguments: dict[str, Any], workspace_path: str, approvals: set[str] | None = None) -> Any:
        filesystem = ProjectFilesystem(workspace_path)

        if name == "list_files":
            return filesystem.list_files(str(arguments.get("path", ".")))
        if name == "read_file":
            return filesystem.read_file(str(arguments["path"]))
        if name == "write_file":
            return filesystem.write_file(str(arguments["path"]), str(arguments.get("content", "")))
        if name == "run_command":
            return ProjectProcessRunner(workspace_path).run(str(arguments["command"]), approvals)
        if name == "check_port":
            require(Permission.LOCAL_PORTS)
            port = int(arguments["port"])
            return {"port": port, "available": ports.is_available(port)}
        if name == "allocate_port":
            require(Permission.LOCAL_PORTS)
            start = int(arguments.get("start", 8000))
            end = int(arguments.get("end", 9000))
            return {"port": ports.allocate(start, end)}
        if name == "list_processes":
            return processes.list()
        if name == "start_process":
            port_value = arguments.get("port")
            return processes.start(
                command=str(arguments["command"]),
                workspace_path=workspace_path,
                approvals=approvals,
                port=int(port_value) if port_value is not None else None,
            )
        if name == "read_process_output":
            return {"output": processes.read_output(str(arguments["process_id"]))}
        if name == "stop_process":
            return processes.stop(str(arguments["process_id"]), approvals)
        raise ValueError(f"Unknown tool: {name}")


tools = ToolRegistry()
