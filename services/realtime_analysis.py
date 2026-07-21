"""Pure analytical helpers for the real-time analysis view.

State (live entries, timers, Qt signals) lives in the ViewModel; this module holds
the side-effect-free logic: delta/period computation, change tracking, highlight
expiry and per-byte aggregation. Kept Qt-free so it can be unit-tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from models.mux_config import MuxConfigEntry
from services.can_data_parser import FRAME_SCHEMA


REAL_TIME_SCHEMA = dict(FRAME_SCHEMA)
REAL_TIME_SCHEMA["Delta T"] = pl.Float64
REAL_TIME_SCHEMA["_ChangedBytes"] = pl.Utf8


@dataclass
class _LiveEntry:
    row: dict
    compare_payload: tuple
    last_seen_monotonic: float
    first_seen_index: int
    previous_ts: float | None = None
    ever_changed: bool = False
    last_change_monotonic: float | None = None
    unique_values: list[set[str]] | None = None
    byte_change_monotonic: list[float | None] | None = None
    frame_count: int = 0
    period_count: int = 0
    period_sum: float = 0.0
    period_min: float | None = None
    period_max: float | None = None


def _mux_bytes_for_row(row: dict, mux_configs: list[MuxConfigEntry]) -> tuple[int, ...]:
    can_id = str(row.get("ID") or "").upper()
    length = row.get("LEN")
    for cfg in mux_configs:
        if cfg.can_id != can_id:
            continue
        if cfg.length is not None and cfg.length != length:
            continue
        return cfg.mux_bytes
    return ()


def _entry_key(row: dict, mux_bytes: tuple[int, ...]) -> tuple:
    mux_value = tuple(row.get(f"D{i}") for i in mux_bytes)
    return row.get("ID"), row.get("LEN"), mux_value


def _compare_payload(row: dict, mux_bytes: tuple[int, ...]) -> tuple:
    # Raw D{i} values (int or None), compared only for equality -- no string
    # conversion needed, and none wanted: str(v) here would collapse a real
    # zero byte and a missing byte to the same falsy-derived "" (they must stay
    # distinct, same as the old hex-string form where "00" was never falsy).
    ignored = set(mux_bytes)
    return tuple(row.get(f"D{i}") for i in range(8) if i not in ignored)


def rekey_live_entries(
    entries: dict[tuple, "_LiveEntry"],
    id_to_entries: dict[str, list["_LiveEntry"]],
    pending: list[tuple[tuple, tuple, "_LiveEntry"]],
) -> None:
    """Move each (old_key, new_key, entry) to its recomputed key after a mux
    reconfiguration. If two entries collapse onto the same new key, discard the loser
    from id_to_entries too -- otherwise it lingers unreachable via entries yet still
    counted in aggregated per-CAN-ID stats, permanently contaminating them.
    """
    for key, _new_key, _entry in pending:
        entries.pop(key, None)
    seen: set[tuple] = set()
    for _key, new_key, entry in pending:
        if new_key in seen:
            can_id = str(entry.row.get("ID") or "").upper()
            bucket = id_to_entries.get(can_id)
            if bucket:
                id_to_entries[can_id] = [e for e in bucket if e is not entry]
            continue
        seen.add(new_key)
        entries[new_key] = entry


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _changed_byte_indexes(
    previous_row: dict,
    current_row: dict,
    *,
    ignored_indexes: set[int] | None = None,
) -> tuple[int, ...]:
    ignored = ignored_indexes or set()
    changed: list[int] = []
    for index in range(8):
        if index in ignored:
            continue
        column = f"D{index}"
        if previous_row.get(column) != current_row.get(column):
            changed.append(index)
    return tuple(changed)


def _with_delta_t(row: dict, delta_t: float | None, changed_bytes: tuple[int, ...] = ()) -> dict:
    updated = dict(row)
    updated["Delta T"] = delta_t
    updated["_ChangedBytes"] = ",".join(str(index) for index in changed_bytes)
    return updated


def _empty_unique_sets() -> list[set[str]]:
    return [set() for _ in range(8)]


def _update_unique_history(entry: _LiveEntry, row: dict) -> None:
    if entry.unique_values is None:
        entry.unique_values = _empty_unique_sets()
    for index in range(8):
        value = row.get(f"D{index}")
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        entry.unique_values[index].add(text.upper())


def _changed_bytes_from_row(row: dict) -> tuple[int, ...]:
    raw = str(row.get("_ChangedBytes") or "").strip()
    if not raw:
        return ()
    values: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            values.append(int(token))
        except ValueError:
            continue
    return tuple(values)


def _active_highlighted_bytes(
    per_byte_ts: list[float | None] | None,
    *,
    now: float,
    hold_ms: int,
) -> tuple[int, ...]:
    if not per_byte_ts:
        return ()
    hold_seconds = max(0.0, float(hold_ms) / 1000.0)
    active: list[int] = []
    for index, ts in enumerate(per_byte_ts):
        if ts is None:
            continue
        if now - ts <= hold_seconds:
            active.append(index)
    return tuple(active)


def _update_entry_period_stats(entry: _LiveEntry, delta_t: float | None, row: dict) -> None:
    if delta_t is None or delta_t < 0:
        return
    entry.period_count = int(entry.period_count) + 1
    entry.period_sum = float(entry.period_sum) + float(delta_t)
    entry.period_min = float(delta_t) if entry.period_min is None else min(float(entry.period_min), float(delta_t))
    entry.period_max = float(delta_t) if entry.period_max is None else max(float(entry.period_max), float(delta_t))


def _aggregate_frame_period(entries: list[_LiveEntry]) -> tuple[float | None, float | None, float | None, int]:
    count = 0
    total = 0.0
    min_v: float | None = None
    max_v: float | None = None
    for entry in entries:
        if int(entry.period_count or 0) <= 0:
            continue
        count += int(entry.period_count or 0)
        total += float(entry.period_sum or 0.0)
        if entry.period_min is not None:
            min_v = float(entry.period_min) if min_v is None else min(min_v, float(entry.period_min))
        if entry.period_max is not None:
            max_v = float(entry.period_max) if max_v is None else max(max_v, float(entry.period_max))
    avg_v = (total / count) if count > 0 else None
    return min_v, max_v, avg_v, count


def _aggregate_unique_counts(entries: list[_LiveEntry]) -> list[int]:
    merged = [set() for _ in range(8)]
    for entry in entries:
        if not entry.unique_values:
            continue
        for idx in range(8):
            merged[idx].update(entry.unique_values[idx] or set())
    return [len(v) for v in merged]


def _aggregate_mux_ignored_indexes(entries: list[_LiveEntry], mux_configs: list[MuxConfigEntry]) -> set[int]:
    ignored: set[int] = set()
    for entry in entries:
        can_id = str(entry.row.get("ID") or "").upper()
        length = entry.row.get("LEN")
        for cfg in mux_configs:
            if cfg.can_id != can_id:
                continue
            if cfg.length is not None and cfg.length != length:
                continue
            ignored.update(int(x) for x in cfg.mux_bytes)
    return ignored


def _fmt_period(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.6f}"


