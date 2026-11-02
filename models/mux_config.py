from __future__ import annotations

from collections.abc import Iterable
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


def normalize_mux_config_entries(configs: Iterable[MuxConfigEntry]) -> list[MuxConfigEntry]:
    normalized: set[MuxConfigEntry] = set()
    configured_rules: dict[tuple[str, int | None], tuple[int, ...]] = {}
    for config in configs:
        can_id = str(config.can_id or "").strip().upper()
        if not can_id or any(char not in "0123456789ABCDEF" for char in can_id):
            raise ValueError(f"Invalid CAN ID '{config.can_id}'. Use hexadecimal digits.")
        if int(can_id, 16) > 0x1FFFFFFF:
            raise ValueError(f"Invalid CAN ID '{can_id}'.")
        length = config.length
        if length is not None:
            if isinstance(length, bool) or not isinstance(length, int):
                raise ValueError(f"Invalid LEN '{length}' for CAN ID {can_id}; use an integer.")
            if length < 1 or length > 8:
                raise ValueError(f"Invalid LEN '{length}' for CAN ID {can_id}; use 1 to 8.")
        if any(isinstance(index, bool) or not isinstance(index, int) for index in config.mux_bytes):
            raise ValueError(f"Invalid MUX bytes for CAN ID {can_id}; byte indexes must be integers.")
        mux_bytes = tuple(sorted(set(config.mux_bytes)))
        if not mux_bytes or any(index < 0 or index > 7 for index in mux_bytes):
            raise ValueError(f"Invalid MUX bytes for CAN ID {can_id}; use byte indexes 0 to 7.")
        if length is not None and mux_bytes[-1] >= length:
            raise ValueError(f"MUX byte is outside LEN {length} for CAN ID {can_id}.")
        key = (can_id, length)
        previous = configured_rules.get(key)
        if previous is not None and previous != mux_bytes:
            raise ValueError(f"Conflicting MUX rules for CAN ID {can_id} and LEN {length}.")
        configured_rules[key] = mux_bytes
        normalized.add(MuxConfigEntry(can_id=can_id, length=length, mux_bytes=mux_bytes))
    return sorted(
        normalized,
        key=lambda item: (item.can_id, item.length is None, item.length or -1, item.mux_bytes),
    )
