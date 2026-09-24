import subprocess

from app.core.permissions import Permission, require
from app.sandbox.path_guard import ProjectPathGuard

MAX_OUTPUT_CHARS = 12_000
COMMAND_TIMEOUT_SECONDS = 30


class ProjectProcessRunner:
    def __init__(self, workspace_path: str):
        self.guard = ProjectPathGuard(workspace_path)

    def run(self, command: str, approvals: set[str] | None = None) -> dict[str, object]:
        require(Permission.TERMINAL_EXECUTE, approvals)
        completed = subprocess.run(
            command,
            cwd=self.guard.ensure_root(),
            shell=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-MAX_OUTPUT_CHARS:],
            "stderr": completed.stderr[-MAX_OUTPUT_CHARS:],
        }
