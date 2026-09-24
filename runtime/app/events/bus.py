from collections import deque
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4


class EventBus:
    def __init__(self, max_events: int = 500):
        self._events = deque(maxlen=max_events)
        self._lock = Lock()

    def emit(self, event_type: str, **payload: object) -> dict[str, object]:
        event = {
            "id": str(uuid4()),
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        with self._lock:
            self._events.append(event)
        return event

    def recent(self, limit: int = 100) -> list[dict[str, object]]:
        with self._lock:
            return list(self._events)[-limit:]


events = EventBus()
