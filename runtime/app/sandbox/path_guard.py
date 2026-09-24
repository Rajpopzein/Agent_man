from pathlib import Path

from app.core.permissions import PermissionDenied


class ProjectPathGuard:
    def __init__(self, workspace_path: str):
        self.root = Path(workspace_path).expanduser().resolve()

    def ensure_root(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def resolve(self, relative_path: str = ".") -> Path:
        root = self.ensure_root()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise PermissionDenied(
                f"Path escapes project workspace: {relative_path}"
            ) from exc
        return target
