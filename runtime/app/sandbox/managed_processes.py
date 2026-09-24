import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.core.config import settings
from app.core.permissions import Permission, require
from app.sandbox.path_guard import ProjectPathGuard
from app.sandbox.ports import ports

MAX_OUTPUT_CHARS = 12_000


@dataclass
class ManagedProcess:
    id: str
    command: str
    workspace_path: str
    process: subprocess.Popen
    log_path: Path
    port: int | None = None

    def snapshot(self) -> dict[str, object]:
        exit_code = self.process.poll()
        return {
            "id": self.id,
            "command": self.command,
            "workspace_path": self.workspace_path,
            "pid": self.process.pid,
            "port": self.port,
            "status": "running" if exit_code is None else "exited",
            "exit_code": exit_code,
        }


class ManagedProcessRegistry:
    def __init__(self):
        self._items: dict[str, ManagedProcess] = {}
        self._lock = Lock()

    def start(
        self,
        *,
        command: str,
        workspace_path: str,
        approvals: set[str] | None = None,
        port: int | None = None,
    ) -> dict[str, object]:
        require(Permission.TERMINAL_EXECUTE, approvals)
        root = ProjectPathGuard(workspace_path).ensure_root()

        reserved_port = None
        if port is not None:
            reserved_port = ports.reserve(port)

        process_id = str(uuid4())
        log_dir = settings.data_dir / "process-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{process_id}.log"

        creationflags = 0
        start_new_session = False
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            start_new_session = True

        try:
            with log_path.open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    shell=True,
                    stdout=log,
                    stderr=log,
                    text=True,
                    creationflags=creationflags,
                    start_new_session=start_new_session,
                )
        except Exception:
            if reserved_port is not None:
                ports.release(reserved_port)
            raise

        item = ManagedProcess(
            id=process_id,
            command=command,
            workspace_path=str(root),
            process=process,
            log_path=log_path,
            port=reserved_port,
        )
        with self._lock:
            self._items[process_id] = item
        return item.snapshot()

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            items = list(self._items.values())
        return [item.snapshot() for item in items]

    def read_output(self, process_id: str) -> str:
        item = self._get(process_id)
        if not item.log_path.exists():
            return ""
        return item.log_path.read_text(encoding="utf-8", errors="replace")[-MAX_OUTPUT_CHARS:]

    def stop(
        self,
        process_id: str,
        approvals: set[str] | None = None,
    ) -> dict[str, object]:
        require(Permission.TERMINAL_EXECUTE, approvals)
        item = self._get(process_id)

        if item.process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(item.process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(item.process.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass

            try:
                item.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                item.process.kill()

        if item.port is not None:
            ports.release(item.port)
        return item.snapshot()

    def _get(self, process_id: str) -> ManagedProcess:
        with self._lock:
            item = self._items.get(process_id)
        if item is None:
            raise KeyError(f"Unknown process: {process_id}")
        return item


processes = ManagedProcessRegistry()
