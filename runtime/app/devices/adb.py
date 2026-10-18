from __future__ import annotations

import io
import os
import platform
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from urllib.request import Request, urlopen
import zipfile

from app.core.config import settings


_MAX_DOWNLOAD_BYTES = 150_000_000
_INSTALL_LOCK = threading.Lock()

_PLATFORM_TOOLS_URLS = {
    "windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
    "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
}


class AdbManager:
    def __init__(
        self,
        root: Path | None = None,
        system: str | None = None,
    ):
        self.root = root or settings.data_dir / "tools" / "android"
        self.system = (system or platform.system()).lower()

    @property
    def executable_name(self) -> str:
        return "adb.exe" if self.system == "windows" else "adb"

    @property
    def managed_path(self) -> Path:
        return self.root / "platform-tools" / self.executable_name

    def _download_url(self) -> str:
        url = _PLATFORM_TOOLS_URLS.get(self.system)
        if not url:
            raise RuntimeError(
                "Automatic ADB bootstrap is not supported on "
                + self.system
            )
        return url

    def locate(self) -> tuple[Path, str] | None:
        override = os.getenv("AGENT_MAN_ADB_PATH", "").strip()
        if override:
            candidate = Path(override).expanduser()
            if candidate.is_file():
                return candidate.resolve(), "configured"

        managed = self.managed_path
        if managed.is_file():
            return managed.resolve(), "agent_man"

        found = shutil.which("adb")
        if found:
            return Path(found).resolve(), "path"
        return None

    def status(self) -> dict[str, object]:
        located = self.locate()
        return {
            "installed": located is not None,
            "path": str(located[0]) if located else "",
            "source": located[1] if located else "",
            "install_root": str(self.root),
            "requires_admin": False,
        }

    def ensure_installed(self) -> dict[str, object]:
        located = self.locate()
        if located:
            return {
                "installed": True,
                "downloaded": False,
                "path": str(located[0]),
                "source": located[1],
                "requires_admin": False,
            }

        with _INSTALL_LOCK:
            located = self.locate()
            if located:
                return {
                    "installed": True,
                    "downloaded": False,
                    "path": str(located[0]),
                    "source": located[1],
                    "requires_admin": False,
                }

            self.root.mkdir(parents=True, exist_ok=True)
            request = Request(
                self._download_url(),
                headers={"User-Agent": "Agent-Man/0.1"},
            )
            with urlopen(request, timeout=60) as response:
                archive_bytes = response.read(_MAX_DOWNLOAD_BYTES + 1)
            if len(archive_bytes) > _MAX_DOWNLOAD_BYTES:
                raise RuntimeError(
                    "Android Platform Tools download exceeded the safety limit"
                )

            staging = Path(
                tempfile.mkdtemp(
                    prefix=".platform-tools-",
                    dir=str(self.root),
                )
            )
            try:
                with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                    for member in archive.infolist():
                        member_path = Path(member.filename)
                        if (
                            member_path.is_absolute()
                            or ".." in member_path.parts
                            or not member_path.parts
                            or member_path.parts[0] != "platform-tools"
                        ):
                            raise RuntimeError(
                                "Unexpected path in Android Platform Tools archive"
                            )
                    archive.extractall(staging)

                extracted = staging / "platform-tools"
                executable = extracted / self.executable_name
                if not executable.is_file():
                    raise RuntimeError(
                        "Downloaded Android Platform Tools archive "
                        "does not contain ADB"
                    )

                target = self.root / "platform-tools"
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(extracted), str(target))

                installed = target / self.executable_name
                if self.system != "windows":
                    installed.chmod(0o755)
            finally:
                shutil.rmtree(staging, ignore_errors=True)

        return {
            "installed": True,
            "downloaded": True,
            "path": str(self.managed_path.resolve()),
            "source": "agent_man",
            "requires_admin": False,
        }

    def _run(
        self,
        arguments: list[str],
        timeout: float = 20.0,
    ) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
        install = self.ensure_installed()
        executable = str(install["path"])

        creationflags = 0
        if self.system == "windows":
            creationflags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )

        completed = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=creationflags,
        )
        if completed.returncode != 0:
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "ADB command failed"
            )
            raise RuntimeError(detail)
        return install, completed

    def version(self) -> dict[str, object]:
        install, completed = self._run(["version"])
        return {
            **install,
            "version": completed.stdout.strip(),
        }

    def devices(self) -> dict[str, object]:
        install, completed = self._run(["devices", "-l"])
        rows: list[dict[str, str]] = []

        for raw_line in completed.stdout.splitlines():
            line = raw_line.strip()
            if not line or line.lower().startswith(
                "list of devices attached"
            ):
                continue

            parts = line.split()
            serial = parts[0]
            state = parts[1] if len(parts) > 1 else "unknown"
            detail_tokens = parts[2:] if len(parts) > 2 else []
            details: dict[str, str] = {}
            for token in detail_tokens:
                if ":" in token:
                    key, value = token.split(":", 1)
                    details[key] = value

            rows.append(
                {
                    "serial": serial,
                    "state": state,
                    "model": details.get("model", ""),
                    "product": details.get("product", ""),
                    "device": details.get("device", ""),
                    "transport_id": details.get("transport_id", ""),
                }
            )

        next_action = ""
        if not rows:
            next_action = (
                "Connect the Android device and enable USB debugging."
            )
        elif any(row["state"] == "unauthorized" for row in rows):
            next_action = (
                "Unlock the Android device and accept the USB debugging prompt."
            )
        elif any(row["state"] != "device" for row in rows):
            next_action = (
                "Resolve the reported ADB device state before sending commands."
            )

        return {
            **install,
            "devices": rows,
            "count": len(rows),
            "next_action": next_action,
        }


adb_manager = AdbManager()
