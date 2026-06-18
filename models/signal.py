from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DataType = Literal["uint", "int", "float32"]


@dataclass
class Signal:
    name: str
    can_id: str | None = None
    start_bit: int = 0
    length: int = 2
    le: bool = True
    scale: float = 1.0
    offset: float = 0.0
    mux_bytes: int = 0
    mux_start: int = 0
    mux_value: int | None = None
    type_data: DataType = "uint"
