from dataclasses import dataclass
from typing import Any

from app.sandbox.filesystem import ProjectFilesystem
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
    ToolDefinition("run_command", "Run a shell command from the project workspace.", "execute", {"command": "shell command"}),
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
        raise ValueError(f"Unknown tool: {name}")


tools = ToolRegistry()
