from types import SimpleNamespace

from app.devices.serial import SerialDeviceBroker


class FakeSerial:
    def __init__(
        self,
        *,
        port,
        baudrate,
        timeout,
        write_timeout,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.is_open = True
        self._read_buffer = bytearray(b"hello\n")
        self.written = bytearray()

    @property
    def in_waiting(self):
        return len(self._read_buffer)

    def read(self, size):
        data = bytes(self._read_buffer[:size])
        del self._read_buffer[:size]
        return data

    def write(self, payload):
        self.written.extend(payload)
        return len(payload)

    def flush(self):
        return None

    def close(self):
        self.is_open = False


def _port(device="COM3"):
    return SimpleNamespace(
        device=device,
        name=device,
        description="USB Serial Device",
        hwid="USB VID:PID=303A:1001",
        vid=0x303A,
        pid=0x1001,
        serial_number="ABC123",
        manufacturer="Test Vendor",
        product="Test Serial",
        interface=None,
    )


def test_serial_broker_lists_metadata(monkeypatch):
    monkeypatch.setattr(
        "app.devices.serial.list_ports.comports",
        lambda: [_port()],
    )
    broker = SerialDeviceBroker()

    ports = broker.list_ports()
    assert len(ports) == 1
    assert ports[0]["device"] == "COM3"
    assert ports[0]["vid"] == 0x303A
    assert ports[0]["pid"] == 0x1001
    assert ports[0]["active_session_id"] is None


def test_serial_broker_open_read_write_close(monkeypatch):
    monkeypatch.setattr(
        "app.devices.serial.list_ports.comports",
        lambda: [_port()],
    )
    monkeypatch.setattr(
        "app.devices.serial.serial.Serial",
        FakeSerial,
    )
    broker = SerialDeviceBroker()

    opened = broker.open(
        device="COM3",
        baudrate=115200,
        timeout_ms=50,
    )
    session_id = opened["session_id"]
    assert opened["device"] == "COM3"
    assert opened["is_open"] is True

    read = broker.read(session_id, max_bytes=32)
    assert read["text"] == "hello\n"
    assert read["bytes_read"] == 6

    written = broker.write(
        session_id,
        text="PING",
        newline=True,
    )
    assert written["bytes_written"] == 5
    assert written["hex"] == "50 49 4e 47 0a"

    sessions = broker.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id

    closed = broker.close(session_id)
    assert closed["closed"] is True
    assert broker.list_sessions() == []


def test_serial_broker_rejects_unenumerated_port(monkeypatch):
    monkeypatch.setattr(
        "app.devices.serial.list_ports.comports",
        lambda: [_port("COM3")],
    )
    broker = SerialDeviceBroker()

    try:
        broker.open(device="COM99")
    except ValueError as exc:
        assert "not currently enumerated" in str(exc)
    else:
        raise AssertionError("Expected unenumerated port rejection")
