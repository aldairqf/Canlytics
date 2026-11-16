from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from collections import deque


@dataclass(frozen=True)
class ErrorDiagnosticsSnapshot:
    counts: dict[str, int]
    total: int
    rate_per_minute: float
    classes: dict[str, int] = field(default_factory=dict)


class ErrorFrameCounter:
    """Thread-safe O(chunk) counters for bus and transport/application errors."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._counts: Counter[str] = Counter()
        self._classes: Counter[str] = Counter()
        self._window_seconds = float(window_seconds)
        self._events = deque()
        self._imported = False
        self._lock = Lock()

    def ingest(self, frames) -> ErrorDiagnosticsSnapshot:
        now = monotonic()
        with self._lock:
            for frame in frames:
                kind = str(getattr(frame, "error_type", "bus"))
                self._record_locked(kind, now)
                for category in decode_can_error_classes(getattr(frame, "can_id", 0), getattr(frame, "data", b"")):
                    self._classes[category] += 1
            return self.snapshot_locked(now)

    def record(self, kind: str, timestamp: float | None = None, can_id: int = 0,
               data: bytes = b"") -> ErrorDiagnosticsSnapshot:
        now = monotonic()
        with self._lock:
            if timestamp is not None:
                self._imported = True
            self._record_locked(kind, now if timestamp is None else float(timestamp))
            for category in decode_can_error_classes(can_id, data):
                self._classes[category] += 1
            return self.snapshot_locked(now if timestamp is None else float(timestamp))

    def _record_locked(self, kind: str, timestamp: float) -> None:
        self._counts[kind] += 1
        self._events.append(timestamp)

    def snapshot(self) -> ErrorDiagnosticsSnapshot:
        with self._lock:
            return self.snapshot_locked(monotonic())

    def snapshot_locked(self, now: float) -> ErrorDiagnosticsSnapshot:
        total = sum(self._counts.values())
        if self._imported:
            elapsed = max(1.0, self._events[-1] - self._events[0]) if self._events else 1.0
            rate = len(self._events) * 60.0 / elapsed
        else:
            while self._events and now - self._events[0] > self._window_seconds:
                self._events.popleft()
            rate = len(self._events) * 60.0 / self._window_seconds
        return ErrorDiagnosticsSnapshot(dict(self._counts), total, rate, dict(self._classes))

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._classes.clear()
            self._events.clear()
            self._imported = False


def decode_can_error_classes(can_id: int, data: bytes) -> tuple[str, ...]:
    flags = int(can_id) & 0x1FFFFFFF
    classes = []
    for mask, name in ((0x002, "lost_arbitration"), (0x004, "controller"), (0x008, "protocol"),
                       (0x010, "transceiver"), (0x020, "ack"), (0x040, "bus_off"),
                       (0x080, "bus_error"), (0x100, "restarted"), (0x001, "tx_timeout")):
        if flags & mask:
            classes.append(name)
    if len(data) > 0 and data[0]:
        classes.append("lost_arbitration")
    if len(data) > 1 and data[1]:
        classes.append("controller")
    if len(data) > 2 and data[2]:
        classes.append("protocol")
    if len(data) > 3 and data[3]:
        classes.append("protocol")
    if len(data) > 4 and data[4] & 0x0F:
        classes.append("transceiver")
    return tuple(dict.fromkeys(classes))
