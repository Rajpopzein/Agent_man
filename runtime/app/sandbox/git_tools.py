import subprocess

from app.core.permissions import Permission, require
from app.sandbox.path_guard import ProjectPathGuard

MAX_OUTPUT_CHARS = 12000


class ProjectGit:
    def __init__(self, workspace_path: str):
        self.root = ProjectPathGuard(workspace_path).ensure_root()

    def _run(self, args: list[str]) -> dict[str, object]:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return {
            "command": "git " + " ".join(args),
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-MAX_OUTPUT_CHARS:],
            "stderr": completed.stderr[-MAX_OUTPUT_CHARS:],
        }

    def status(self) -> dict[str, object]:
        require(Permission.PROJECT_READ)
        return self._run(["status", "--short", "--branch"])

    def diff(self, staged: bool = False) -> dict[str, object]:
        require(Permission.PROJECT_READ)
        args = ["diff"]
        if staged:
            args.append("--staged")
        return self._run(args)

    def commit(
        self,
        message: str,
        approvals: set[str] | None = None,
    ) -> dict[str, object]:
        require(Permission.TERMINAL_EXECUTE, approvals)
        return self._run(["commit", "-am", message])
