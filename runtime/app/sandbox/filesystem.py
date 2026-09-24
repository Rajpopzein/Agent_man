from app.core.permissions import Permission, require
from app.sandbox.path_guard import ProjectPathGuard

MAX_READ_BYTES = 200_000
MAX_WRITE_BYTES = 500_000
MAX_LIST_ENTRIES = 200


class ProjectFilesystem:
    def __init__(self, workspace_path: str):
        self.guard = ProjectPathGuard(workspace_path)

    def list_files(self, path: str = ".") -> list[dict[str, object]]:
        require(Permission.PROJECT_READ)
        target = self.guard.resolve(path)
        if not target.exists():
            return []
        if not target.is_dir():
            raise ValueError(f"Not a directory: {path}")
        rows: list[dict[str, object]] = []
        for item in sorted(target.iterdir(), key=lambda value: value.name.lower()):
            rows.append({
                "name": item.name,
                "path": str(item.relative_to(self.guard.root)),
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
            if len(rows) >= MAX_LIST_ENTRIES:
                break
        return rows

    def read_file(self, path: str) -> str:
        require(Permission.PROJECT_READ)
        target = self.guard.resolve(path)
        if not target.is_file():
            raise FileNotFoundError(path)
        if target.stat().st_size > MAX_READ_BYTES:
            raise ValueError(f"File exceeds {MAX_READ_BYTES} byte V1 read limit: {path}")
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> dict[str, object]:
        require(Permission.PROJECT_WRITE)
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_WRITE_BYTES:
            raise ValueError(f"Content exceeds {MAX_WRITE_BYTES} byte V1 write limit")
        target = self.guard.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "path": str(target.relative_to(self.guard.root)),
            "bytes_written": len(encoded),
        }
