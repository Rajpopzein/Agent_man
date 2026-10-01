import base64
import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )
    return blob, buffer


def _windows_crypto():
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL

    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


class SecretStore:
    def __init__(self, root: Path | None = None):
        self.root = root or settings.data_dir / "secrets"

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.secret"

    def _fernet(self) -> Fernet:
        configured = os.getenv("AGENT_MAN_SECRET_KEY", "").strip()
        if not configured:
            raise RuntimeError(
                "AGENT_MAN_SECRET_KEY is required for API-key storage "
                "on non-Windows runtimes"
            )
        try:
            return Fernet(configured.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "AGENT_MAN_SECRET_KEY must be a valid Fernet key"
            ) from exc

    def set(self, key: str, value: str) -> None:
        if os.name == "nt":
            encrypted = self._encrypt_windows(value)
        else:
            encrypted = self._fernet().encrypt(value.encode("utf-8"))

        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        path.write_text(
            base64.b64encode(encrypted).decode("ascii"),
            encoding="ascii",
        )
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def get(self, key: str) -> str | None:
        path = self._path(key)
        if not path.exists():
            return None

        encrypted = base64.b64decode(
            path.read_text(encoding="ascii")
        )

        if os.name == "nt":
            return self._decrypt_windows(encrypted)

        try:
            plaintext = self._fernet().decrypt(encrypted)
        except InvalidToken as exc:
            raise RuntimeError(
                "Stored API key cannot be decrypted with "
                "AGENT_MAN_SECRET_KEY"
            ) from exc
        return plaintext.decode("utf-8")

    def _encrypt_windows(self, value: str) -> bytes:
        plaintext = value.encode("utf-8")
        input_blob, input_buffer = _blob(plaintext)
        output_blob = _DataBlob()
        crypt32, kernel32 = _windows_crypto()

        if not crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "Agent Man",
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            return ctypes.string_at(
                output_blob.pbData,
                output_blob.cbData,
            )
        finally:
            kernel32.LocalFree(output_blob.pbData)
            _ = input_buffer

    def _decrypt_windows(self, encrypted: bytes) -> str:
        input_blob, input_buffer = _blob(encrypted)
        output_blob = _DataBlob()
        crypt32, kernel32 = _windows_crypto()

        if not crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            plaintext = ctypes.string_at(
                output_blob.pbData,
                output_blob.cbData,
            )
        finally:
            kernel32.LocalFree(output_blob.pbData)
            _ = input_buffer

        return plaintext.decode("utf-8")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


secrets = SecretStore()
