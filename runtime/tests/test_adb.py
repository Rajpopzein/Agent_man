import io
from pathlib import Path
import zipfile

from app.devices.adb import AdbManager


def _platform_tools_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "platform-tools/adb.exe",
            b"portable-adb",
        )
        archive.writestr(
            "platform-tools/AdbWinApi.dll",
            b"dll",
        )
        archive.writestr(
            "platform-tools/AdbWinUsbApi.dll",
            b"dll",
        )
    return buffer.getvalue()


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.payload[:size] if size >= 0 else self.payload


def test_adb_bootstrap_is_portable_and_requires_no_admin(
    monkeypatch,
    tmp_path: Path,
):
    payload = _platform_tools_zip()
    monkeypatch.setattr(
        "app.devices.adb.shutil.which",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "app.devices.adb.urlopen",
        lambda _request, timeout=60: _Response(payload),
    )

    manager = AdbManager(
        root=tmp_path / "android",
        system="windows",
    )
    result = manager.ensure_installed()

    assert result["installed"] is True
    assert result["downloaded"] is True
    assert result["requires_admin"] is False
    assert Path(str(result["path"])).is_file()
    assert Path(str(result["path"])).name == "adb.exe"
    assert (
        tmp_path
        / "android"
        / "platform-tools"
        / "AdbWinApi.dll"
    ).is_file()


def test_adb_status_uses_existing_managed_install(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        "app.devices.adb.shutil.which",
        lambda _name: None,
    )
    managed = (
        tmp_path
        / "android"
        / "platform-tools"
        / "adb.exe"
    )
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"adb")

    manager = AdbManager(
        root=tmp_path / "android",
        system="windows",
    )
    status = manager.status()

    assert status["installed"] is True
    assert status["source"] == "agent_man"
    assert status["requires_admin"] is False
    assert status["path"] == str(managed.resolve())
