import json
from pathlib import Path

from app.sandbox.path_guard import ProjectPathGuard
from app.sandbox.processes import ProjectProcessRunner


class DevelopmentTools:
    def __init__(self, workspace_path: str):
        self.guard = ProjectPathGuard(workspace_path)
        self.root = self.guard.ensure_root()
        self.runner = ProjectProcessRunner(workspace_path)

    def _package_scripts(self) -> dict[str, str]:
        package_json = self.root / "package.json"
        if not package_json.is_file():
            return {}
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        scripts = payload.get("scripts") or {}
        return {str(key): str(value) for key, value in scripts.items()}

    def run_tests(
        self,
        approvals: set[str] | None = None,
        command: str | None = None,
    ):
        if command:
            return self.runner.run(command, approvals)
        scripts = self._package_scripts()
        if "test" in scripts:
            return self.runner.run("npm test -- --runInBand", approvals)
        if (
            (self.root / "pyproject.toml").exists()
            or (self.root / "requirements.txt").exists()
            or (self.root / "pytest.ini").exists()
        ):
            return self.runner.run("python -m pytest -q", approvals)
        raise ValueError("Could not infer a test command for this project")

    def run_build(
        self,
        approvals: set[str] | None = None,
        command: str | None = None,
    ):
        if command:
            return self.runner.run(command, approvals)
        scripts = self._package_scripts()
        if "build" in scripts:
            return self.runner.run("npm run build", approvals)
        raise ValueError("Could not infer a build command for this project")

    def lint(
        self,
        approvals: set[str] | None = None,
        command: str | None = None,
    ):
        if command:
            return self.runner.run(command, approvals)
        scripts = self._package_scripts()
        if "lint" in scripts:
            return self.runner.run("npm run lint", approvals)
        if (self.root / "pyproject.toml").exists():
            return self.runner.run("python -m ruff check .", approvals)
        raise ValueError("Could not infer a lint command for this project")
