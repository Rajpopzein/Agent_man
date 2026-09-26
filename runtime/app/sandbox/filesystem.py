import fnmatch

from app.core.permissions import Permission, require
from app.sandbox.path_guard import ProjectPathGuard

MAX_READ_BYTES = 200_000
MAX_WRITE_BYTES = 500_000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_RESULTS = 100


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
            raise ValueError(
                f"File exceeds {MAX_READ_BYTES} byte V1 read limit: {path}"
            )
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> dict[str, object]:
        require(Permission.PROJECT_WRITE)
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_WRITE_BYTES:
            raise ValueError(
                f"Content exceeds {MAX_WRITE_BYTES} byte V1 write limit"
            )
        target = self.guard.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "path": str(target.relative_to(self.guard.root)),
            "bytes_written": len(encoded),
        }

    def edit_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
    ) -> dict[str, object]:
        require(Permission.PROJECT_WRITE)
        content = self.read_file(path)
        occurrences = content.count(old_text)
        if occurrences == 0:
            raise ValueError("Text to replace was not found")
        if occurrences > 1 and not replace_all:
            raise ValueError(
                "Text occurs more than once; set replace_all=true or use a more specific match"
            )
        updated = content.replace(
            old_text,
            new_text,
            -1 if replace_all else 1,
        )
        result = self.write_file(path, updated)
        result["replacements"] = occurrences if replace_all else 1
        return result

    def search_files(
        self,
        query: str,
        path: str = ".",
        pattern: str = "*",
    ) -> list[dict[str, object]]:
        require(Permission.PROJECT_READ)
        root = self.guard.resolve(path)
        if not root.exists():
            return []
        results: list[dict[str, object]] = []
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            if not fnmatch.fnmatch(item.name, pattern):
                continue
            if item.stat().st_size > MAX_READ_BYTES:
                continue
            try:
                lines = item.read_text(
                    encoding="utf-8",
                    errors="ignore",
                ).splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if query.lower() in line.lower():
                    results.append({
                        "path": str(item.relative_to(self.guard.root)),
                        "line": line_number,
                        "text": line[:500],
                    })
                    if len(results) >= MAX_SEARCH_RESULTS:
                        return results
        return results

    def delete_path(
        self,
        path: str,
        approvals: set[str] | None = None,
    ) -> dict[str, object]:
        require(Permission.PROJECT_DELETE, approvals)
        target = self.guard.resolve(path)
        if not target.exists():
            raise FileNotFoundError(path)
        if target.is_dir():
            if any(target.iterdir()):
                raise ValueError(
                    "V1 only deletes empty directories; remove contents explicitly first"
                )
            target.rmdir()
            kind = "directory"
        else:
            target.unlink()
            kind = "file"
        return {"path": path, "deleted": True, "type": kind}
