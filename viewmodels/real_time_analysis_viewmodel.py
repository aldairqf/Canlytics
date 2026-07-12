from __future__ import annotations

import time

import polars as pl
from PySide6.QtCore import QObject, QTimer, Signal as QtSignal

from models.mux_config import MuxConfigEntry
from services.realtime_analysis import (
    REAL_TIME_SCHEMA,
    _LiveEntry,
    _active_highlighted_bytes,
    _aggregate_frame_period,
    _aggregate_mux_ignored_indexes,
    _aggregate_unique_counts,
    _changed_byte_indexes,
    _changed_bytes_from_row,
    _compare_payload,
    _empty_unique_sets,
    _entry_key,
    _fmt_period,
    _mux_bytes_for_row,
    _safe_float,
    _update_entry_period_stats,
    _update_unique_history,
    _with_delta_t,
    compute_changed_ids_delta,
)

DEFAULT_HIGHLIGHT_HOLD_MS = 5000


class RealTimeAnalysisViewModel(QObject):
    dataframe_changed = QtSignal(object)
    can_ids_changed = QtSignal(list)
    changed_ids_changed = QtSignal(object)
    # Emits a ChangedIdsDelta whenever changed_ids_changed does -- tells a
    # "Changes Only" consumer (the CAN ID panel) exactly how to move (resync
    # to the full set, or just check the newly-changed ids) without it having
    # to track a previous snapshot or decide "grew vs shrunk" itself.
    changed_ids_delta_changed = QtSignal(object)
    enabled_changed = QtSignal(bool)
    show_only_changing_changed = QtSignal(bool)
    detect_changes_changed = QtSignal(bool)
    refresh_interval_changed = QtSignal(int)
    highlight_hold_changed = QtSignal(int)
    mux_configuration_changed = QtSignal()
    change_summary_changed = QtSignal(str)

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
        self._last_emitted_changed_ids: frozenset[str] = frozenset()
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
    def changed_ids(self) -> set[str]:
        return set(self._changed_ids)

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
            mux_bytes = _mux_bytes_for_row(row, self._mux_configs)
            entry_key = _entry_key(row, mux_bytes)
            compare_payload = _compare_payload(row, mux_bytes)
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
        self.change_summary_changed.emit(self._change_summary_text())

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
        self.reset_change_detection()

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
            mux_bytes = _mux_bytes_for_row(entry.row, self._mux_configs)
            new_key = _entry_key(entry.row, mux_bytes)
            entry.ever_changed = False
            entry.last_change_monotonic = None
            entry.compare_payload = _compare_payload(entry.row, mux_bytes)
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
        changed_now = frozenset(self._changed_ids)
        if changed_now != self._last_emitted_changed_ids:
            delta = compute_changed_ids_delta(self._last_emitted_changed_ids, changed_now)
            self._last_emitted_changed_ids = changed_now
            self.changed_ids_changed.emit(set(changed_now))
            self.changed_ids_delta_changed.emit(delta)

    def _emit_if_dirty(self) -> None:
        if self._entries:
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
        mux_bytes = _mux_bytes_for_row(row, self._mux_configs)
        entry_key = _entry_key(row, mux_bytes)
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

    @staticmethod
    def _empty_df() -> pl.DataFrame:
        return pl.DataFrame({key: [] for key in REAL_TIME_SCHEMA.keys()}, schema=REAL_TIME_SCHEMA)
