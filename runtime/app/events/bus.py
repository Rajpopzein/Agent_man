from collections import deque
from datetime import datetime, timezone
from threading import Condition, Lock
from uuid import uuid4


class EventBus:
    def __init__(self, max_events: int = 500):
        self._events = deque(maxlen=max_events)
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._sequence = 0

    def emit(self, event_type: str, **payload: object) -> dict[str, object]:
        with self._condition:
            self._sequence += 1
            event = {
                "id": str(uuid4()),
                "sequence": self._sequence,
                "type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **payload,
            }
            self._events.append(event)
            self._condition.notify_all()
            return dict(event)

    def recent(self, limit: int = 100) -> list[dict[str, object]]:
        with self._lock:
            return [dict(event) for event in list(self._events)[-limit:]]

    def current_sequence(self) -> int:
        with self._lock:
            return self._sequence

    def wait_since(
        self,
        sequence: int,
        timeout: float = 15.0,
        project_id: str | None = None,
    ) -> tuple[int, list[dict[str, object]]]:
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence > sequence,
                timeout=timeout,
            )

            cursor = self._sequence
            batch = [
                dict(event)
                for event in self._events
                if int(event.get("sequence", 0)) > sequence
            ]

        if project_id is not None:
            batch = [
                event
                for event in batch
                if event.get("project_id") == project_id
            ]

        return cursor, batch


events = EventBus()
