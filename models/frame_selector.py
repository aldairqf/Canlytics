from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from utils.can_id import can_id_to_int

SelectorMode = Literal["exact", "j1939", "bam"]


@dataclass
class FrameSelector:
    selected_id: str | None = None
    mode: SelectorMode = "exact"
    pgn: int | None = None
    target_id: int | None = None

    def selected_id_int(self) -> int | None:
        if not self.selected_id:
            return None
        try:
            return can_id_to_int(self.selected_id)
        except (TypeError, ValueError):
            return None
