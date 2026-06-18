from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MuxConfigEntry:
    can_id: str
    length: int | None
    mux_bytes: tuple[int, ...]


def parse_mux_bytes(raw: str) -> tuple[int, ...]:
    text = (raw or "").strip()
    if not text:
        return ()

    result: list[int] = []
    for chunk in text.split(","):
        part = chunk.strip()
        if not part:
            continue
        try:
            index = int(part)
        except ValueError as exc:
            raise ValueError(f"Invalid MUX byte '{part}'. Use byte indexes like 0,1,2.") from exc
        if index < 0 or index > 7:
            raise ValueError(f"Invalid MUX byte '{part}'. Valid byte indexes are 0 to 7.")
        if index not in result:
            result.append(index)
    return tuple(result)
