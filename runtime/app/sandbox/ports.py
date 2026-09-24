import socket
from threading import Lock


class PortRegistry:
    def __init__(self):
        self._reserved: set[int] = set()
        self._lock = Lock()

    def is_available(self, port: int) -> bool:
        if not 1 <= port <= 65535:
            return False
        with self._lock:
            if port in self._reserved:
                return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def reserve(self, port: int) -> int:
        if not self.is_available(port):
            raise ValueError(f"Port {port} is not available")
        with self._lock:
            self._reserved.add(port)
        return port

    def allocate(self, start: int = 8000, end: int = 9000) -> int:
        if start < 1 or end > 65535 or start > end:
            raise ValueError("Invalid port range")
        for port in range(start, end + 1):
            if self.is_available(port):
                return self.reserve(port)
        raise RuntimeError(f"No free port found between {start} and {end}")

    def release(self, port: int) -> None:
        with self._lock:
            self._reserved.discard(port)

    def reserved(self) -> list[int]:
        with self._lock:
            return sorted(self._reserved)


ports = PortRegistry()
