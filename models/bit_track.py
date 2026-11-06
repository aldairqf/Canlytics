from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BitTrack:
    can_id: str
    byte_index: int
    bit_index: int

    @property
    def label(self) -> str:
        return f"{self.can_id} · D{self.byte_index} · b{self.bit_index}"
