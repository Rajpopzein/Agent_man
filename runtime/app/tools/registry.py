from dataclasses import dataclass
from typing import Any

from app.core.permissions import Permission, PermissionDenied, require
from app.devices.serial import serial_devices
from app.sandbox.development import DevelopmentTools
from app.sandbox.filesystem import ProjectFilesystem
from app.sandbox.git_tools import ProjectGit
from app.sandbox.managed_processes import processes
from app.sandbox.network import internet
from app.sandbox.ports import ports
from app.sandbox.processes import ProjectProcessRunner


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: str
    risk: str
    version: str
    arguments: dict[str, str]


TOOL_DEFINITIONS = [
    ToolDefinition("list_files", "List files and folders inside the project.", "filesystem", "read", "1.0.0", {"path": "relative directory path"}),
    ToolDefinition("read_file", "Read a UTF-8 text file inside the project.", "filesystem", "read", "1.0.0", {"path": "relative file path"}),
    ToolDefinition("write_file", "Create or replace a UTF-8 text file inside the project.", "filesystem", "write", "1.0.0", {"path": "relative file path", "content": "complete file content"}),
    ToolDefinition("edit_file", "Replace text inside a project file.", "filesystem", "write", "1.0.0", {"path": "relative file path", "old_text": "text to replace", "new_text": "replacement text", "replace_all": "optional boolean"}),
    ToolDefinition("search_files", "Search project text files for a query.", "filesystem", "read", "1.0.0", {"query": "text to search", "path": "relative directory", "pattern": "filename glob such as *.py"}),
    ToolDefinition("delete_path", "Delete a file or an empty directory inside the project.", "filesystem", "destructive", "1.0.0", {"path": "relative path"}),
    ToolDefinition("run_command", "Run a shell command and wait for completion.", "terminal", "execute", "1.0.0", {"command": "shell command"}),
    ToolDefinition("git_status", "Read Git working tree status.", "git", "read", "1.0.0", {}),
    ToolDefinition("git_diff", "Read Git diff for working tree or staged changes.", "git", "read", "1.0.0", {"staged": "optional boolean"}),
    ToolDefinition("git_commit", "Commit already tracked Git changes with a message.", "git", "execute", "1.0.0", {"message": "commit message"}),
    ToolDefinition("run_tests", "Run the project's test command.", "development", "execute", "1.0.0", {"command": "optional explicit test command"}),
    ToolDefinition("run_build", "Run the project's build command.", "development", "execute", "1.0.0", {"command": "optional explicit build command"}),
    ToolDefinition("lint", "Run the project's lint command.", "development", "execute", "1.0.0", {"command": "optional explicit lint command"}),
    ToolDefinition("check_port", "Check whether a local TCP port is free.", "runtime", "read", "1.0.0", {"port": "port number"}),
    ToolDefinition("allocate_port", "Reserve a free local TCP port for Agent Man.", "runtime", "write", "1.0.0", {"start": "first port", "end": "last port"}),
    ToolDefinition("list_processes", "List background processes started by Agent Man.", "runtime", "read", "1.0.0", {}),
    ToolDefinition("start_process", "Start a background process in the project workspace.", "runtime", "execute", "1.0.0", {"command": "shell command", "port": "optional port to reserve"}),
    ToolDefinition("read_process_output", "Read recent output from a managed process.", "runtime", "read", "1.0.0", {"process_id": "managed process id"}),
    ToolDefinition("stop_process", "Stop a managed background process.", "runtime", "execute", "1.0.0", {"process_id": "managed process id"}),
    ToolDefinition("http_get", "Fetch textual content from a public internet URL. Local/private network destinations are blocked.", "network", "network", "1.0.0", {"url": "public http/https URL"}),
    ToolDefinition("list_serial_ports", "List serial/COM ports detected by the local operating system, including USB metadata when available.", "hardware", "read", "1.0.0", {}),
    ToolDefinition("serial_open", "Open an enumerated serial/COM port and create a managed hardware session.", "hardware", "hardware", "1.0.0", {"device": "enumerated device such as COM3", "baudrate": "optional baudrate, default 115200", "timeout_ms": "optional read timeout up to 2000 ms", "write_timeout_ms": "optional write timeout up to 2000 ms"}),
    ToolDefinition("serial_list_sessions", "List serial sessions opened by Agent Man.", "hardware", "read", "1.0.0", {}),
    ToolDefinition("serial_read", "Read bytes from an Agent Man serial session.", "hardware", "hardware", "1.0.0", {"session_id": "serial session id", "max_bytes": "optional maximum bytes, default 4096", "timeout_ms": "optional read timeout up to 2000 ms"}),
    ToolDefinition("serial_write", "Write UTF-8 text or hexadecimal bytes to an Agent Man serial session.", "hardware", "hardware", "1.0.0", {"session_id": "serial session id", "text": "UTF-8 text payload; mutually exclusive with hex_data", "hex_data": "hex bytes such as 01 ff 0a; mutually exclusive with text", "newline": "optional boolean; append newline to text"}),
    ToolDefinition("serial_close", "Close an Agent Man serial session and release the COM port.", "hardware", "write", "1.0.0", {"session_id": "serial session id"}),
]


def definition_map() -> dict[str, ToolDefinition]:
    return {tool.name: tool for tool in TOOL_DEFINITIONS}


def catalog_for_prompt(
    allowed_names: set[str] | None = None,
) -> str:
    lines = []
    for tool in TOOL_DEFINITIONS:
        if allowed_names is not None and tool.name not in allowed_names:
            continue
        args = ", ".join(
            f"{key}: {value}"
            for key, value in tool.arguments.items()
        )
        lines.append(
            f"- {tool.name} [{tool.risk}] ({tool.category}): "
            f"{tool.description} Args: {args}"
        )
    return "\n".join(lines)


class ToolRegistry:
    def execute(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        workspace_path: str,
        approvals: set[str] | None = None,
        allowed_names: set[str] | None = None,
    ) -> Any:
        if allowed_names is not None and name not in allowed_names:
            raise PermissionDenied(
                f"Tool is disabled or not assigned to this agent: {name}"
            )

        filesystem = ProjectFilesystem(workspace_path)

        if name == "list_files":
            return filesystem.list_files(str(arguments.get("path", ".")))
        if name == "read_file":
            return filesystem.read_file(str(arguments["path"]))
        if name == "write_file":
            return filesystem.write_file(
                str(arguments["path"]),
                str(arguments.get("content", "")),
            )
        if name == "edit_file":
            return filesystem.edit_file(
                str(arguments["path"]),
                str(arguments["old_text"]),
                str(arguments.get("new_text", "")),
                bool(arguments.get("replace_all", False)),
            )
        if name == "search_files":
            return filesystem.search_files(
                str(arguments["query"]),
                str(arguments.get("path", ".")),
                str(arguments.get("pattern", "*")),
            )
        if name == "delete_path":
            return filesystem.delete_path(
                str(arguments["path"]),
                approvals,
            )
        if name == "run_command":
            return ProjectProcessRunner(workspace_path).run(
                str(arguments["command"]),
                approvals,
            )
        if name == "git_status":
            return ProjectGit(workspace_path).status()
        if name == "git_diff":
            return ProjectGit(workspace_path).diff(
                bool(arguments.get("staged", False))
            )
        if name == "git_commit":
            return ProjectGit(workspace_path).commit(
                str(arguments["message"]),
                approvals,
            )
        if name == "run_tests":
            return DevelopmentTools(workspace_path).run_tests(
                approvals,
                str(arguments["command"])
                if arguments.get("command")
                else None,
            )
        if name == "run_build":
            return DevelopmentTools(workspace_path).run_build(
                approvals,
                str(arguments["command"])
                if arguments.get("command")
                else None,
            )
        if name == "lint":
            return DevelopmentTools(workspace_path).lint(
                approvals,
                str(arguments["command"])
                if arguments.get("command")
                else None,
            )
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
                port=int(port_value)
                if port_value is not None
                else None,
            )
        if name == "read_process_output":
            return {
                "output": processes.read_output(
                    str(arguments["process_id"])
                )
            }
        if name == "stop_process":
            return processes.stop(
                str(arguments["process_id"]),
                approvals,
            )
        if name == "http_get":
            return internet.get(
                str(arguments["url"]),
                approvals,
            )
        if name == "list_serial_ports":
            return serial_devices.list_ports()
        if name == "serial_open":
            require(Permission.SERIAL_ACCESS, approvals)
            return serial_devices.open(
                device=str(arguments["device"]),
                baudrate=int(arguments.get("baudrate", 115200)),
                timeout_ms=int(arguments.get("timeout_ms", 250)),
                write_timeout_ms=int(
                    arguments.get("write_timeout_ms", 1000)
                ),
            )
        if name == "serial_list_sessions":
            return serial_devices.list_sessions()
        if name == "serial_read":
            require(Permission.SERIAL_ACCESS, approvals)
            timeout_value = arguments.get("timeout_ms")
            return serial_devices.read(
                str(arguments["session_id"]),
                max_bytes=int(arguments.get("max_bytes", 4096)),
                timeout_ms=(
                    int(timeout_value)
                    if timeout_value is not None
                    else None
                ),
            )
        if name == "serial_write":
            require(Permission.SERIAL_ACCESS, approvals)
            return serial_devices.write(
                str(arguments["session_id"]),
                text=(
                    str(arguments["text"])
                    if arguments.get("text") is not None
                    else None
                ),
                hex_data=(
                    str(arguments["hex_data"])
                    if arguments.get("hex_data") is not None
                    else None
                ),
                newline=bool(arguments.get("newline", False)),
            )
        if name == "serial_close":
            return serial_devices.close(
                str(arguments["session_id"])
            )
        raise ValueError(f"Unknown tool: {name}")


tools = ToolRegistry()
