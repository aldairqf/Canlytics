from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from services.can_send import ResolvedFrame


@dataclass(frozen=True)
class SourceFrame:
    """One received frame before application timestamp policy is applied."""

    can_id: int
    data: bytes
    timestamp: float | None = None
    bus: str = ""
    is_error: bool = False
    length: int | None = None


class CanSource(Protocol):
    """Qt-free lifecycle and frame I/O contract for CAN capture sources."""

    bitrate: int | None
    finished: bool

    def open(self, *, canceled: Callable[[], bool], status: Callable[[str], None]) -> None: ...

    def receive(self, timeout: float) -> SourceFrame | None: ...

    def send(self, frame: ResolvedFrame) -> None: ...

    def close(self) -> None: ...
