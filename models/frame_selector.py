from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from utils.can_id import can_id_to_int

SelectorMode = Literal["exact", "j1939", "bam"]


@dataclass
class FrameSelector:
    selected_id: Optional[str] = None
    mode: SelectorMode = "exact"
    pgn: Optional[int] = None
    target_id: Optional[int] = None

    def selected_id_int(self) -> Optional[int]:
        if not self.selected_id:
            return None
        try:
            return can_id_to_int(self.selected_id)
        except (TypeError, ValueError):
            return None
