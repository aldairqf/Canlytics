from __future__ import annotations

import time
from dataclasses import dataclass

import polars as pl
from PySide6.QtCore import QObject, QTimer, Signal

from services.can_data_parser import FRAME_SCHEMA


REAL_TIME_SCHEMA = dict(FRAME_SCHEMA)
REAL_TIME_SCHEMA["Delta T"] = pl.Float64


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


class RealTimeAnalysisViewModel(QObject):
    dataframe_changed = Signal(object)
    can_ids_changed = Signal(list)
    enabled_changed = Signal(bool)
    show_only_changing_changed = Signal(bool)
    mux_configuration_changed = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._enabled = False
        self._show_only_changing = False
        self._mux_configs: list[MuxConfigEntry] = []
        self._entries: dict[tuple, _LiveEntry] = {}
        self._id_order: dict[str, int] = {}
        self._changed_ids: set[str] = set()
        self._df = self._empty_df()
        self._next_first_seen_index = 0

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self._emit_current_view)
        self._refresh_timer.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def show_only_changing(self) -> bool:
        return self._show_only_changing

    @property
    def mux_configs(self) -> list[MuxConfigEntry]:
        return list(self._mux_configs)

    def mux_configuration_summary(self) -> str:
        if not self._mux_configs:
            return "No MUX configuration"
        return f"{len(self._mux_configs)} MUX rule(s)"

    def ingest_df(self, df: pl.DataFrame) -> None:
        if df is None or df.is_empty():
            return

        now = time.monotonic()
        for row in df.iter_rows(named=True):
            mux_bytes = self._mux_bytes_for_row(row)
            entry_key = self._entry_key(row, mux_bytes)
            compare_payload = self._compare_payload(row, mux_bytes)
            current = self._entries.get(entry_key)

            if current is None:
                can_id = str(row.get("ID") or "")
                if can_id not in self._id_order:
                    self._id_order[can_id] = len(self._id_order)
                has_existing_id_entries = any(
                    str(existing.row.get("ID") or "") == can_id
                    for existing in self._entries.values()
                )
                if has_existing_id_entries:
                    self._changed_ids.add(can_id)
                    for existing in self._entries.values():
                        if str(existing.row.get("ID") or "") == can_id:
                            existing.ever_changed = True
                self._entries[entry_key] = _LiveEntry(
                    row=_with_delta_t(dict(row), None),
                    compare_payload=compare_payload,
                    last_seen_monotonic=now,
                    first_seen_index=self._next_first_seen_index,
                    previous_ts=_safe_float(row.get("TS")),
                    ever_changed=can_id in self._changed_ids or has_existing_id_entries,
                )
                self._next_first_seen_index += 1
                continue
            current_ts = _safe_float(row.get("TS"))
            delta_t = None if current.previous_ts is None or current_ts is None else round(current_ts - current.previous_ts, 6)
            current.row = _with_delta_t(dict(row), delta_t)
            current.previous_ts = current_ts
            current.last_seen_monotonic = now
            if current.compare_payload != compare_payload:
                current.compare_payload = compare_payload
                current.ever_changed = True
                can_id = str(row.get("ID") or "")
                self._changed_ids.add(can_id)
                for other in self._entries.values():
                    if str(other.row.get("ID") or "") == can_id:
                        other.ever_changed = True

        self._emit_current_view()

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self.enabled_changed.emit(enabled)

    def set_show_only_changing(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._show_only_changing == enabled:
            return
        self._show_only_changing = enabled
        self.show_only_changing_changed.emit(enabled)
        self._emit_current_view()

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
        self._changed_ids.clear()
        for key, entry in list(self._entries.items()):
            mux_bytes = self._mux_bytes_for_row(entry.row)
            new_key = self._entry_key(entry.row, mux_bytes)
            entry.ever_changed = False
            entry.compare_payload = self._compare_payload(entry.row, mux_bytes)
            entry.row = _with_delta_t(dict(entry.row), entry.row.get("Delta T"))
            if new_key != key:
                self._entries.pop(key, None)
                self._entries[new_key] = entry
        self._emit_current_view()

    def clear(self) -> None:
        self._entries.clear()
        self._id_order.clear()
        self._changed_ids.clear()
        self._next_first_seen_index = 0
        self._emit_current_view()

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

        self.dataframe_changed.emit(self._df)
        self.can_ids_changed.emit(self._current_ids())

    def _current_ids(self) -> list[str]:
        if self._df.is_empty() or "ID" not in self._df.columns:
            return []
        return sorted(self._df["ID"].unique().to_list())

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


def _with_delta_t(row: dict, delta_t: float | None) -> dict:
    updated = dict(row)
    updated["Delta T"] = delta_t
    return updated
