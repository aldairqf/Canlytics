from __future__ import annotations

import time
from dataclasses import dataclass

import polars as pl
from PySide6.QtCore import QObject, QTimer, Signal

from services.can_data_parser import FRAME_SCHEMA


REAL_TIME_SCHEMA = dict(FRAME_SCHEMA)
REAL_TIME_SCHEMA["Delta T"] = pl.Float64
REAL_TIME_SCHEMA["_ChangedBytes"] = pl.Utf8
DEFAULT_HIGHLIGHT_HOLD_MS = 5000


@dataclass(frozen=True)
class MuxConfigEntry:
    can_id: str
    length: int | None
    mux_bytes: tuple[int, ...]


@dataclass
class _LiveEntry:
    row: dict
    compare_payload: tuple[str, ...]
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


class RealTimeAnalysisViewModel(QObject):
    dataframe_changed = Signal(object)
    can_ids_changed = Signal(list)
    enabled_changed = Signal(bool)
    show_only_changing_changed = Signal(bool)
    detect_changes_changed = Signal(bool)
    refresh_interval_changed = Signal(int)
    highlight_hold_changed = Signal(int)
    mux_configuration_changed = Signal()
    change_summary_changed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._enabled = False
        self._show_only_changing = False
        self._detect_changes = False
        self._mux_configs: list[MuxConfigEntry] = []
        self._entries: dict[tuple, _LiveEntry] = {}
        self._id_order: dict[str, int] = {}
        self._changed_ids: set[str] = set()
        self._df = self._empty_df()
        self._next_first_seen_index = 0
        self._dirty = False
        self._last_emitted_ids: tuple[str, ...] = ()
        self._highlight_hold_ms = DEFAULT_HIGHLIGHT_HOLD_MS

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(100)
        self._refresh_timer.timeout.connect(self._emit_if_dirty)
        self._refresh_timer.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def show_only_changing(self) -> bool:
        return self._show_only_changing

    @property
    def detect_changes(self) -> bool:
        return self._detect_changes

    @property
    def mux_configs(self) -> list[MuxConfigEntry]:
        return list(self._mux_configs)

    def mux_configuration_summary(self) -> str:
        if not self._mux_configs:
            return "No MUX"
        return f"{len(self._mux_configs)} rule(s)"

    @property
    def refresh_interval_ms(self) -> int:
        return int(self._refresh_timer.interval())

    @property
    def highlight_hold_ms(self) -> int:
        return int(self._highlight_hold_ms)

    def ingest_df(self, df: pl.DataFrame) -> None:
        if df is None or df.is_empty():
            return

        now = time.monotonic()
        changed = False
        for row in df.iter_rows(named=True):
            mux_bytes = self._mux_bytes_for_row(row)
            entry_key = self._entry_key(row, mux_bytes)
            compare_payload = self._compare_payload(row, mux_bytes)
            current = self._entries.get(entry_key)

            if current is None:
                can_id = str(row.get("ID") or "")
                if can_id not in self._id_order:
                    self._id_order[can_id] = len(self._id_order)
                self._entries[entry_key] = _LiveEntry(
                    row=_with_delta_t(dict(row), None),
                    compare_payload=compare_payload,
                    last_seen_monotonic=now,
                    first_seen_index=self._next_first_seen_index,
                    previous_ts=_safe_float(row.get("TS")),
                    ever_changed=self._detect_changes and (can_id in self._changed_ids),
                    last_change_monotonic=None,
                    unique_values=_empty_unique_sets(),
                    byte_change_monotonic=[None for _ in range(8)],
                    frame_count=1,
                    period_count=0,
                    period_sum=0.0,
                    period_min=None,
                    period_max=None,
                )
                _update_unique_history(self._entries[entry_key], row)
                self._next_first_seen_index += 1
                changed = True
                continue
            current_ts = _safe_float(row.get("TS"))
            delta_t = None if current.previous_ts is None or current_ts is None else round(current_ts - current.previous_ts, 6)
            _update_entry_period_stats(current, delta_t, row)
            changed_bytes = (
                _changed_byte_indexes(current.row, row, ignored_indexes=set(mux_bytes))
                if self._detect_changes
                else ()
            )
            payload_changed = current.compare_payload != compare_payload if self._detect_changes else False
            previous_changed_bytes = _changed_bytes_from_row(current.row) if self._detect_changes else ()
            if not changed_bytes and not payload_changed and current.previous_ts == current_ts:
                current.last_seen_monotonic = now
                continue
            _update_unique_history(current, row)
            changed_bytes_for_row = changed_bytes
            if self._detect_changes:
                if current.byte_change_monotonic is None:
                    current.byte_change_monotonic = [None for _ in range(8)]
                for byte_index in changed_bytes:
                    if 0 <= int(byte_index) < 8:
                        current.byte_change_monotonic[int(byte_index)] = now
                changed_bytes_for_row = _active_highlighted_bytes(
                    current.byte_change_monotonic,
                    now=now,
                    hold_ms=self._highlight_hold_ms,
                )
                if not changed_bytes_for_row and previous_changed_bytes:
                    changed_bytes_for_row = previous_changed_bytes
            current.row = _with_delta_t(
                dict(row),
                delta_t,
                changed_bytes_for_row,
            )
            current.previous_ts = current_ts
            current.last_seen_monotonic = now
            current.frame_count = int(current.frame_count) + 1
            changed = True
            if self._detect_changes:
                # Anchor highlight hold to actual highlighted-byte changes.
                if changed_bytes:
                    current.last_change_monotonic = now
                if payload_changed:
                    current.ever_changed = True
                    can_id = str(row.get("ID") or "")
                    self._changed_ids.add(can_id)
                current.compare_payload = compare_payload
            else:
                current.compare_payload = compare_payload

        if changed:
            self._dirty = True

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self.enabled_changed.emit(enabled)

    def set_show_only_changing(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled and not self._detect_changes:
            enabled = False
        if self._show_only_changing == enabled:
            return
        self._show_only_changing = enabled
        self.show_only_changing_changed.emit(enabled)
        self._emit_current_view()

    def set_detect_changes(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._detect_changes == enabled:
            return
        self._detect_changes = enabled
        if not enabled and self._show_only_changing:
            self._show_only_changing = False
            self.show_only_changing_changed.emit(False)
        self._reset_change_baseline()
        self.detect_changes_changed.emit(enabled)
        self._emit_current_view()

    def set_refresh_interval_ms(self, interval_ms: int) -> None:
        interval_ms = max(10, min(int(interval_ms), 5000))
        if self._refresh_timer.interval() == interval_ms:
            return
        self._refresh_timer.setInterval(interval_ms)
        self.refresh_interval_changed.emit(interval_ms)

    def set_highlight_hold_ms(self, hold_ms: int) -> None:
        hold_ms = max(100, min(int(hold_ms), 10000))
        if self._highlight_hold_ms == hold_ms:
            return
        self._highlight_hold_ms = hold_ms
        self.highlight_hold_changed.emit(hold_ms)

    def set_mux_configuration(self, configs: list[MuxConfigEntry]) -> None:
        normalized = sorted(
            {
                MuxConfigEntry(
                    can_id=(cfg.can_id or "").strip().upper(),
                    length=cfg.length,
                    mux_bytes=tuple(sorted(set(cfg.mux_bytes))),
                )
                for cfg in configs
                if (cfg.can_id or "").strip() and cfg.mux_bytes
            },
            key=lambda item: (item.can_id, item.length is None, item.length if item.length is not None else -1, item.mux_bytes),
        )
        if normalized == self._mux_configs:
            return
        self._mux_configs = normalized
        self.reset_change_detection()
        self.mux_configuration_changed.emit()

    def reset_change_detection(self) -> None:
        self._reset_change_baseline()
        self._emit_current_view()

    def reset_realtime_state(self) -> None:
        self._reset_change_baseline()
        self._emit_current_view()

    def clear(self) -> None:
        self._entries.clear()
        self._id_order.clear()
        self._changed_ids.clear()
        self._next_first_seen_index = 0
        self._last_emitted_ids = ()
        self._emit_current_view()

    def _reset_change_baseline(self) -> None:
        self._changed_ids.clear()
        for key, entry in list(self._entries.items()):
            mux_bytes = self._mux_bytes_for_row(entry.row)
            new_key = self._entry_key(entry.row, mux_bytes)
            entry.ever_changed = False
            entry.last_change_monotonic = None
            entry.compare_payload = self._compare_payload(entry.row, mux_bytes)
            entry.unique_values = _empty_unique_sets()
            entry.byte_change_monotonic = [None for _ in range(8)]
            entry.frame_count = 1
            entry.period_count = 0
            entry.period_sum = 0.0
            entry.period_min = None
            entry.period_max = None
            _update_unique_history(entry, entry.row)
            entry.row = _with_delta_t(
                dict(entry.row),
                entry.row.get("Delta T"),
                (),
            )
            if new_key != key:
                self._entries.pop(key, None)
                self._entries[new_key] = entry

    def _emit_current_view(self) -> None:
        rows: list[dict] = []

        ordered_entries = sorted(
            self._entries.values(),
            key=lambda entry: (
                self._id_order.get(str(entry.row.get("ID") or ""), 10**9),
                entry.first_seen_index,
            ),
        )
        for entry in ordered_entries:
            if self._show_only_changing and not entry.ever_changed:
                continue
            rows.append(entry.row)

        if rows:
            self._df = pl.DataFrame(rows, schema=REAL_TIME_SCHEMA, orient="row")
        else:
            self._df = self._empty_df()

        self._dirty = False
        self.dataframe_changed.emit(self._df)
        self.change_summary_changed.emit(self._change_summary_text())
        current_ids = tuple(self._current_ids())
        if current_ids != self._last_emitted_ids:
            self._last_emitted_ids = current_ids
            self.can_ids_changed.emit(list(current_ids))

    def _emit_if_dirty(self) -> None:
        self._clear_expired_highlights()
        if not self._dirty:
            return
        self._emit_current_view()

    def _clear_expired_highlights(self) -> None:
        if not self._detect_changes:
            return
        now = time.monotonic()
        expired = False
        for entry in self._entries.values():
            if entry.byte_change_monotonic is None:
                continue
            active = _active_highlighted_bytes(
                entry.byte_change_monotonic,
                now=now,
                hold_ms=self._highlight_hold_ms,
            )
            current = _changed_bytes_from_row(entry.row)
            if tuple(current) == tuple(active):
                continue
            entry.row = _with_delta_t(dict(entry.row), entry.row.get("Delta T"), active)
            expired = True
        if expired:
            self._dirty = True

    def _change_summary_text(self) -> str:
        if not self._detect_changes:
            return "Change detection OFF"
        changed_count = len(self._changed_ids)
        total_ids = len(self._id_order)
        if self._show_only_changing:
            return f"Changed IDs: {changed_count}/{total_ids} (filtered)"
        return f"Changed IDs: {changed_count}/{total_ids}"

    def _current_ids(self) -> list[str]:
        if self._df.is_empty() or "ID" not in self._df.columns:
            return []
        return sorted(self._df["ID"].unique().to_list())

    def build_details(self, selected_ids: set[str] | list[str] | tuple[str, ...]) -> str:
        ids = sorted({str(v).strip().upper() for v in (selected_ids or []) if str(v).strip()})
        if not ids:
            return "Select a row in the table (or one CAN ID) to show details."

        target_id = ids[0]
        entries = [
            entry
            for entry in self._entries.values()
            if str(entry.row.get("ID") or "").upper() == target_id
        ]
        if not entries:
            return f"Details: no live data for ID {target_id}."

        lines: list[str] = [f"ID {target_id}"]
        if len(ids) > 1:
            lines.append(f"Using clicked/first ID from {len(ids)} selected.")
        lines.append("")

        frame_min, frame_max, frame_avg, frame_count = _aggregate_frame_period(entries)
        lines.append("Frame Period [s]")
        lines.append(f"  min: {_fmt_period(frame_min)}")
        lines.append(f"  max: {_fmt_period(frame_max)}")
        lines.append(f"  avg: {_fmt_period(frame_avg)}")
        lines.append(f"  n  : {frame_count}")
        lines.append("")

        unique_counts = _aggregate_unique_counts(entries)
        mux_ignored = _aggregate_mux_ignored_indexes(entries, self._mux_configs)

        lines.append("Unique values per byte:")
        lines.append(_section_sep(8 * 6))
        lines.append(_format_bytes_line([f"B{i}" for i in range(8)], width=5))
        lines.append(_format_bytes_line(["-----" for _ in range(8)], width=5))
        lines.append(_format_bytes_line(["MUX" if i in mux_ignored else str(unique_counts[i]) for i in range(8)], width=5))
        lines.append(_section_sep(8 * 6))
        lines.append("")

        return "\n".join(lines)

    def build_details_for_row(self, row: dict | None) -> str:
        if not row:
            return self.build_details(())

        target_id = str(row.get("ID") or "").strip().upper()
        if not target_id:
            return self.build_details(())

        mux_bytes = self._mux_bytes_for_row(row)
        entry_key = self._entry_key(row, mux_bytes)
        entry = self._entries.get(entry_key)
        if entry is None:
            return self.build_details([target_id])

        lines: list[str] = [f"ID {target_id}"]
        if mux_bytes:
            mux_desc = ", ".join(f"B{i}={str(row.get(f'B{i}') or '').strip().upper()}" for i in mux_bytes)
            lines.append(f"MUX branch: {mux_desc}")
        lines.append("")

        frame_min, frame_max, frame_avg, frame_count = _aggregate_frame_period([entry])
        lines.append("Frame Period [s]")
        lines.append(f"  min: {_fmt_period(frame_min)}")
        lines.append(f"  max: {_fmt_period(frame_max)}")
        lines.append(f"  avg: {_fmt_period(frame_avg)}")
        lines.append(f"  n  : {frame_count}")
        lines.append("")

        unique_counts = _aggregate_unique_counts([entry])
        mux_ignored = set(int(i) for i in mux_bytes)

        lines.append("Unique values per byte:")
        lines.append(_section_sep(8 * 6))
        lines.append(_format_bytes_line([f"B{i}" for i in range(8)], width=5))
        lines.append(_format_bytes_line(["-----" for _ in range(8)], width=5))
        lines.append(_format_bytes_line(["MUX" if i in mux_ignored else str(unique_counts[i]) for i in range(8)], width=5))
        lines.append(_section_sep(8 * 6))
        lines.append("")

        return "\n".join(lines)

    def details_data_for_selection(self, selected_ids: set[str] | list[str] | tuple[str, ...]) -> dict:
        ids = sorted({str(v).strip().upper() for v in (selected_ids or []) if str(v).strip()})
        if not ids:
            return {"empty": "Select a row in the table (or one CAN ID) to show details."}
        target_id = ids[0]
        entries = [
            entry for entry in self._entries.values() if str(entry.row.get("ID") or "").upper() == target_id
        ]
        if not entries:
            return {"empty": f"No live data for ID {target_id}."}
        return self._build_details_data(
            target_id=target_id,
            entries=entries,
            mux_ignored=_aggregate_mux_ignored_indexes(entries, self._mux_configs),
            subtitle=(f"Using first ID from {len(ids)} selected." if len(ids) > 1 else ""),
        )

    def details_data_for_row(self, row: dict | None) -> dict:
        if not row:
            return {"empty": "Select a row in the table (or one CAN ID) to show details."}
        target_id = str(row.get("ID") or "").strip().upper()
        if not target_id:
            return {"empty": "Select a row in the table (or one CAN ID) to show details."}
        mux_bytes = self._mux_bytes_for_row(row)
        entry_key = self._entry_key(row, mux_bytes)
        entry = self._entries.get(entry_key)
        if entry is None:
            return self.details_data_for_selection([target_id])
        mux_desc = ""
        if mux_bytes:
            mux_desc = ", ".join(f"B{i}={str(row.get(f'B{i}') or '').strip().upper()}" for i in mux_bytes)
        return self._build_details_data(
            target_id=target_id,
            entries=[entry],
            mux_ignored=set(int(i) for i in mux_bytes),
            subtitle=(f"MUX branch: {mux_desc}" if mux_desc else ""),
        )

    def _build_details_data(
        self,
        *,
        target_id: str,
        entries: list[_LiveEntry],
        mux_ignored: set[int],
        subtitle: str = "",
    ) -> dict:
        frame_min, frame_max, frame_avg, frame_count = _aggregate_frame_period(entries)
        unique_counts = _aggregate_unique_counts(entries)
        return {
            "id": target_id,
            "subtitle": subtitle,
            "frame": {
                "min": _fmt_period(frame_min),
                "max": _fmt_period(frame_max),
                "avg": _fmt_period(frame_avg),
                "n": str(frame_count),
            },
            "unique": [("MUX" if i in mux_ignored else str(unique_counts[i])) for i in range(8)],
        }

    def _mux_bytes_for_row(self, row: dict) -> tuple[int, ...]:
        can_id = str(row.get("ID") or "").upper()
        length = row.get("LEN")
        for cfg in self._mux_configs:
            if cfg.can_id != can_id:
                continue
            if cfg.length is not None and cfg.length != length:
                continue
            return cfg.mux_bytes
        return ()

    @staticmethod
    def _entry_key(row: dict, mux_bytes: tuple[int, ...]) -> tuple:
        mux_value = tuple(row.get(f"B{i}") for i in mux_bytes)
        return row.get("ID"), row.get("LEN"), mux_value

    @staticmethod
    def _compare_payload(row: dict, mux_bytes: tuple[int, ...]) -> tuple[str, ...]:
        ignored = set(mux_bytes)
        return tuple(str(row.get(f"B{i}") or "") for i in range(8) if i not in ignored)

    @staticmethod
    def _empty_df() -> pl.DataFrame:
        return pl.DataFrame({key: [] for key in REAL_TIME_SCHEMA.keys()}, schema=REAL_TIME_SCHEMA)


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
        column = f"B{index}"
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
        value = row.get(f"B{index}")
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


def _format_bytes_line(items: list[str], *, width: int = 6) -> str:
    return " ".join(f"{str(item):>{max(3, int(width))}}" for item in items)


def _section_sep(length: int = 40) -> str:
    return "-" * max(20, int(length))
