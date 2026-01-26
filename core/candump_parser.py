from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_CANDUMP_TA = re.compile(
    r"^\((?P<ts>[\d.]+)\)\s+(?P<bus>\S+)\s+(?P<id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]{0,16})\s*$"
)

_CANDUMP_TA_SPACED = re.compile(
    r"^\((?P<ts>[\d.]+)\)\s+(?P<bus>\S+)\s+(?P<id>[0-9A-Fa-f]+)\s+\[(?P<len>\d+)\]\s*(?P<bytes>(?:[0-9A-Fa-f]{2}\s*){0,8})\s*$"
)


def _pad16(data_hex: str) -> str:
    s = (data_hex or "").upper()
    if len(s) >= 16:
        return s[:16]
    return s + ("0" * (16 - len(s)))


@dataclass
class CandumpParser:
    normalize_time: bool = False

    def __post_init__(self) -> None:
        self._t0: Optional[float] = None

    def parse_line(self, line: str) -> Optional[dict]:
        s = (line or "").strip()
        if not s:
            return None

        ts: float
        bus: str
        can_id: str
        data: str
        length: int

        m = _CANDUMP_TA.match(s)
        if m:
            ts = float(m.group("ts"))
            bus = m.group("bus")
            can_id = m.group("id").upper()
            data = (m.group("data") or "").upper()[:16]
            length = len(data) // 2
        else:
            m2 = _CANDUMP_TA_SPACED.match(s)
            if not m2:
                return None

            ts = float(m2.group("ts"))
            bus = m2.group("bus")
            can_id = m2.group("id").upper()

            bytes_str = (m2.group("bytes") or "").strip()
            parts = bytes_str.split() if bytes_str else []
            data = "".join(parts).upper()[:16]

            try:
                declared_len = int(m2.group("len"))
            except ValueError:
                declared_len = len(parts)

            length = min(declared_len, len(parts))

        if self.normalize_time:
            if self._t0 is None:
                self._t0 = ts
            ts = round(ts - self._t0, 6)

        padded = _pad16(data)

        bcols = [padded[i * 2 : i * 2 + 2] for i in range(8)]
        dcols = [int(x, 16) for x in bcols]

        return {
            "TS": float(ts),
            "Bus": bus,
            "ID": can_id,
            "DATA": data,
            "LEN": int(length),
            "B0": bcols[0],
            "B1": bcols[1],
            "B2": bcols[2],
            "B3": bcols[3],
            "B4": bcols[4],
            "B5": bcols[5],
            "B6": bcols[6],
            "B7": bcols[7],
            "D0": dcols[0],
            "D1": dcols[1],
            "D2": dcols[2],
            "D3": dcols[3],
            "D4": dcols[4],
            "D5": dcols[5],
            "D6": dcols[6],
            "D7": dcols[7],
        }
