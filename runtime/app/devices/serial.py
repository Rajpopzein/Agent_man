from __future__ import annotations

from atexit import register
from dataclasses import dataclass
from threading import RLock
from time import time
from uuid import uuid4

import serial
from serial.tools import list_ports

MAX_READ_BYTES = 16_384
MAX_WRITE_BYTES = 8_192
MAX_TIMEOUT_SECONDS = 2.0
MIN_BAUDRATE = 300
MAX_BAUDRATE = 4_000_000


@dataclass
class SerialSession:
    id: str
    device: str
    baudrate: int
    opened_at: float
    serial: serial.Serial


class SerialDeviceBroker:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, SerialSession] = {}

    def list_ports(self) -> list[dict[str, object]]:
        with self._lock:
            active_by_device = {
                session.device: session.id
                for session in self._sessions.values()
                if session.serial.is_open
            }
        result: list[dict[str, object]] = []
        for port in list_ports.comports():
            result.append(
                {
                    "device": port.device,
                    "name": port.name,
                    "description": port.description,
                    "hwid": port.hwid,
                    "vid": port.vid,
                    "pid": port.pid,
                    "serial_number": port.serial_number,
                    "manufacturer": port.manufacturer,
                    "product": port.product,
                    "interface": port.interface,
                    "active_session_id": active_by_device.get(
                        port.device
                    ),
                }
            )
        return result

    def open(
        self,
        *,
        device: str,
        baudrate: int = 115200,
        timeout_ms: int = 250,
        write_timeout_ms: int = 1000,
    ) -> dict[str, object]:
        device = device.strip()
        if not device:
            raise ValueError("Serial device is required")

        available = {
            str(item["device"]): item
            for item in self.list_ports()
        }
        if device not in available:
            raise ValueError(
                "Serial device is not currently enumerated: "
                + device
            )

        baudrate = int(baudrate)
        if not MIN_BAUDRATE <= baudrate <= MAX_BAUDRATE:
            raise ValueError(
                f"Baudrate must be between {MIN_BAUDRATE} "
                f"and {MAX_BAUDRATE}"
            )

        timeout = max(
            0.0,
            min(float(timeout_ms) / 1000.0, MAX_TIMEOUT_SECONDS),
        )
        write_timeout = max(
            0.05,
            min(
                float(write_timeout_ms) / 1000.0,
                MAX_TIMEOUT_SECONDS,
            ),
        )

        with self._lock:
            for session in self._sessions.values():
                if (
                    session.device.lower() == device.lower()
                    and session.serial.is_open
                ):
                    raise RuntimeError(
                        f"{device} is already open in session "
                        f"{session.id}"
                    )

            handle = serial.Serial(
                port=device,
                baudrate=baudrate,
                timeout=timeout,
                write_timeout=write_timeout,
            )
            session_id = str(uuid4())
            self._sessions[session_id] = SerialSession(
                id=session_id,
                device=device,
                baudrate=baudrate,
                opened_at=time(),
                serial=handle,
            )

        return self._view(self._sessions[session_id])

    def list_sessions(self) -> list[dict[str, object]]:
        with self._lock:
            stale = [
                session_id
                for session_id, session in self._sessions.items()
                if not session.serial.is_open
            ]
            for session_id in stale:
                self._sessions.pop(session_id, None)

            return [
                self._view(session)
                for session in self._sessions.values()
            ]

    def read(
        self,
        session_id: str,
        *,
        max_bytes: int = 4096,
        timeout_ms: int | None = None,
    ) -> dict[str, object]:
        session = self._require(session_id)
        max_bytes = max(1, min(int(max_bytes), MAX_READ_BYTES))

        handle = session.serial
        original_timeout = handle.timeout
        if timeout_ms is not None:
            handle.timeout = max(
                0.0,
                min(
                    float(timeout_ms) / 1000.0,
                    MAX_TIMEOUT_SECONDS,
                ),
            )

        try:
            waiting = int(handle.in_waiting or 0)
            size = min(max_bytes, waiting) if waiting > 0 else 1
            data = handle.read(size)
            if data and int(handle.in_waiting or 0) > 0:
                remaining = min(
                    max_bytes - len(data),
                    int(handle.in_waiting or 0),
                )
                if remaining > 0:
                    data += handle.read(remaining)
        finally:
            handle.timeout = original_timeout

        return {
            "session_id": session_id,
            "device": session.device,
            "bytes_read": len(data),
            "text": data.decode("utf-8", errors="replace"),
            "hex": data.hex(" "),
        }

    def write(
        self,
        session_id: str,
        *,
        text: str | None = None,
        hex_data: str | None = None,
        newline: bool = False,
    ) -> dict[str, object]:
        session = self._require(session_id)

        if (text is None) == (hex_data is None):
            raise ValueError(
                "Provide exactly one of text or hex_data"
            )

        if hex_data is not None:
            cleaned = (
                hex_data.replace("0x", "")
                .replace(",", " ")
                .replace("-", " ")
            )
            payload = bytes.fromhex(cleaned)
        else:
            payload = str(text).encode("utf-8")
            if newline:
                payload += b"\n"

        if len(payload) > MAX_WRITE_BYTES:
            raise ValueError(
                f"Serial write is limited to {MAX_WRITE_BYTES} bytes"
            )

        written = session.serial.write(payload)
        session.serial.flush()
        return {
            "session_id": session_id,
            "device": session.device,
            "bytes_written": int(written),
            "hex": payload.hex(" "),
        }

    def close(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                raise KeyError(
                    f"Unknown serial session: {session_id}"
                )
            try:
                if session.serial.is_open:
                    session.serial.close()
            finally:
                return {
                    "session_id": session_id,
                    "device": session.device,
                    "closed": True,
                }

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                if session.serial.is_open:
                    session.serial.close()
            except Exception:
                pass

    def _require(self, session_id: str) -> SerialSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or not session.serial.is_open:
                raise KeyError(
                    f"Unknown or closed serial session: {session_id}"
                )
            return session

    @staticmethod
    def _view(session: SerialSession) -> dict[str, object]:
        return {
            "session_id": session.id,
            "device": session.device,
            "baudrate": session.baudrate,
            "is_open": bool(session.serial.is_open),
            "in_waiting": int(session.serial.in_waiting or 0),
            "opened_at": session.opened_at,
        }


serial_devices = SerialDeviceBroker()


register(serial_devices.close_all)
