from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TraceFilter:
    byte_index: int | None = None
    mask: int | None = None
    value: int | None = None
    dlc: int | None = None
    only_changes: bool = False
