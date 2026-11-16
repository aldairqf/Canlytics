from __future__ import annotations

from bisect import bisect_left
from typing import Callable, Optional

import polars as pl
import numpy as np
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PySide6.QtGui import QColor, QFontDatabase

from services.bam_decode import decode_bam_frame
from viewmodels.dbc_manager_viewmodel import DbcManagerViewModel
from services.signal_formatting import build_decode_display_lines, format_data_bytes
from services.trace_columns import calculate_appended_delta_t, calculate_delta_t
from services.j1939_analysis import pgn_name
from utils.j1939 import J1939
from utils.can_id import can_id_to_int_or_none, format_can_id

# Same throttle idea as data_viewmodel.py's _RECHUNK_EVERY_N_FLUSHES -- rechunk=True
# on every tail-append is an O(total rows) copy; do it periodically instead of on
# every single incoming chunk during streaming.
_RECHUNK_EVERY_N_APPENDS = 20


class TableModel(QAbstractTableModel):
    def __init__(self, columns: list[str], *, optimize_append: bool = True):
        super().__init__()
        self._columns = columns
        self._optimize_append = optimize_append
        self._df = pl.DataFrame({c: [] for c in columns})
        self._decode_enabled = False
        self._expanded_rows: set[int] = set()
        self._dbc_manager: DbcManagerViewModel | None = None
        self._decode_cache: dict[
            int, tuple[tuple, list[dict], str, list[int | None]]
        ] = {}
        self._decode_cache_by_key: dict[
            tuple, tuple[list[dict], str, list[int | None]]
        ] = {}
        self._decode_cache_limit = 2000
        self._fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self._data_display_mode = "bytes"
        self._last_trace_timestamps: dict[str, float] = {}
        self._message_names: dict[str, str | None] = {}
        self._j1939_values_by_id: dict[str, tuple[str | None, str | None, str | None, int | None, str | None]] = {}
        self._visible_j1939_columns: set[str] = set()
        self._sort_column: int | None = None
        self._sort_descending: bool = False
        self._sort_is_applied = False
        self._one_row_per_id_view = False
        self._preserve_sort_once = False
        self._row_foreground: Optional[Callable[[int], QColor | None]] = None
        self._row_background: Optional[Callable[[int], QColor | None]] = None
        self._append_count = 0
        # The vm's own row order, restored when the user clears the header sort.
        self._natural_df: pl.DataFrame | None = None
        self._time_index_times = np.empty(0, dtype=np.float64)
        self._time_index_rows = np.empty(0, dtype=np.int64)
        self._time_index_count = 0

    def set_row_foreground_provider(self, provider: Optional[Callable[[int], QColor | None]]) -> None:
        """Generic per-row foreground-color hook (e.g. Real-Time dims rows the
        current CAN ID filter doesn't consider "changed") -- None disables it."""
        self._row_foreground = provider

    def set_row_background_provider(self, provider: Optional[Callable[[int], QColor | None]]) -> None:
        self._row_background = provider

    def set_dataframe(self, df: pl.DataFrame):
        if df is None:
            self._natural_df = None
            self._sort_is_applied = False
            self.beginResetModel()
            self._df = self._df.clear()
            self._decode_cache.clear()
            self._decode_cache_by_key.clear()
            self._expanded_rows.clear()
            self.endResetModel()
            self._time_index_times = np.empty(0, dtype=np.float64)
            self._time_index_rows = np.empty(0, dtype=np.int64)
            self._time_index_count = 0
            self._last_trace_timestamps.clear()
            return

        df = self._prepare_full_dataframe(df)
        available = [c for c in self._columns if c in df.columns]
        selected = df.select(available)
        for col in self._columns:
            if col not in selected.columns:
                selected = selected.with_columns(pl.lit(None).alias(col))
        new_df = selected.select(self._columns)
        self._natural_df = new_df
        preserve_sort = self._one_row_per_id_view or self._preserve_sort_once
        self._preserve_sort_once = False
        if not self._optimize_append or preserve_sort:
            # BUGS.md B-09: without this, a live-refreshing table (Real-Time Analysis)
            # discards the user's chosen column sort on every tick, because new_df
            # always arrives in the vm's own (unsorted) order. Safe here because
            # optimize_append=False never takes the tail-insert fast path below, whose
            # beginInsertRows() range assumes the vm's original row order.
            new_df = self._apply_active_sort(new_df)
            self._sort_is_applied = self._sort_column is not None
        else:
            self._sort_is_applied = False

        old_h = int(self._df.height)
        new_h = int(new_df.height)

        if old_h == 0 and new_h > 0:
            self.beginInsertRows(QModelIndex(), 0, new_h - 1)
            self._df = new_df
            self.endInsertRows()
            self._rebuild_time_index()
            return

        if old_h > 0 and new_h == old_h:
            self._df = new_df
            if new_h > 0 and self.columnCount() > 0:
                top_left = self.index(0, 0)
                bottom_right = self.index(new_h - 1, self.columnCount() - 1)
                self.dataChanged.emit(top_left, bottom_right)
            self._rebuild_time_index()
            return

        if self._optimize_append and old_h > 0 and new_h > old_h:
            if _same_row_identity(self._df, new_df, old_h):
                existing_new = new_df.slice(0, old_h)
                tail = new_df.slice(old_h, new_h - old_h)
                self._df = existing_new
                if old_h > 0 and self.columnCount() > 0:
                    self.dataChanged.emit(self.index(0, 0), self.index(old_h - 1, self.columnCount() - 1))
                if tail.height > 0:
                    self._append_count += 1
                    do_rechunk = self._append_count % _RECHUNK_EVERY_N_APPENDS == 0
                    self.beginInsertRows(QModelIndex(), old_h, new_h - 1)
                    self._df = pl.concat([self._df, tail], how="vertical", rechunk=do_rechunk)
                    self.endInsertRows()
                    self._append_time_index(tail, old_h)
                return

        self.beginResetModel()
        self._df = new_df
        self._decode_cache.clear()
        self._decode_cache_by_key.clear()
        # _expanded_rows is keyed by row INDEX, not by frame identity -- after a
        # full reset (e.g. the CAN ID filter selection changes) row N no longer
        # refers to the same frame, so treating it as still-expanded computes a
        # fresh (possibly different) line count for content whose row height in
        # the view was set for the OLD row N's line count, garbling the text.
        self._expanded_rows.clear()
        self.endResetModel()
        self._rebuild_time_index()

    def append_rows(self, delta: pl.DataFrame):
        """Append filtered rows without comparing or notifying existing rows."""
        if delta is None or delta.is_empty():
            return
        delta = self._prepare_appended_dataframe(delta)
        available = [c for c in self._columns if c in delta.columns]
        appended = delta.select(available)
        for col in self._columns:
            if col not in appended.columns:
                appended = appended.with_columns(pl.lit(None).alias(col))
        appended = appended.select(self._columns)
        if self._natural_df is None:
            self.set_dataframe(appended)
            return

        new_natural = pl.concat([self._natural_df, appended], how="vertical", rechunk=False)
        self._append_count += 1
        do_rechunk = self._append_count % _RECHUNK_EVERY_N_APPENDS == 0
        if self._sort_column is not None:
            if not self._sort_is_applied:
                self.beginResetModel()
                self._df = self._apply_active_sort(self._df)
                self._decode_cache.clear()
                self._decode_cache_by_key.clear()
                self._expanded_rows.clear()
                self.endResetModel()
                self._rebuild_time_index()
                self._sort_is_applied = True
            self._append_rows_sorted(appended, self._sort_column)
            self._natural_df = new_natural.rechunk() if do_rechunk else new_natural
            if do_rechunk:
                self._df = self._df.rechunk()
            return

        if not self._optimize_append:
            self.beginResetModel()
            self._natural_df = new_natural
            self._df = new_natural
            self._decode_cache.clear()
            self._decode_cache_by_key.clear()
            self._expanded_rows.clear()
            self.endResetModel()
            self._rebuild_time_index()
            return

        old_h = self._df.height
        self.beginInsertRows(QModelIndex(), old_h, old_h + appended.height - 1)
        self._df = pl.concat([self._df, appended], how="vertical", rechunk=do_rechunk)
        self._natural_df = self._df
        self.endInsertRows()
        self._append_time_index(appended, old_h)

    def _append_rows_sorted(self, delta: pl.DataFrame, column_index: int) -> None:
        column = self._columns[column_index]
        if self._df[column].dtype == pl.Null:
            position = self._df.height
            groups = [(position, delta)]
        else:
            sorted_delta = delta.sort(
                column,
                descending=self._sort_descending,
                maintain_order=True,
            )
            positions = self._df[column].search_sorted(
                sorted_delta[column],
                side="right",
                descending=self._sort_descending,
            ).to_list()
            groups = []
            start = 0
            for end in range(1, len(positions) + 1):
                if end == len(positions) or positions[end] != positions[start]:
                    groups.append((int(positions[start]), sorted_delta.slice(start, end - start)))
                    start = end

        if groups:
            group_positions = np.asarray([position for position, _ in groups], dtype=np.int64)
            group_counts = np.asarray([rows.height for _, rows in groups], dtype=np.int64)
            shifts = np.cumsum(group_counts)
            old_rows = self._time_index_rows[:self._time_index_count]
            old_rows += np.where(
                np.searchsorted(group_positions, old_rows, side="right") > 0,
                shifts[np.maximum(np.searchsorted(group_positions, old_rows, side="right") - 1, 0)],
                0,
            )
            self._expanded_rows = self._shift_indices(self._expanded_rows, group_positions, shifts)
            self._decode_cache = self._shift_index_mapping(self._decode_cache, group_positions, shifts)
        pending_times: list[np.ndarray] = []
        pending_rows: list[np.ndarray] = []
        has_timestamp = "TS" in self._columns
        for group_index in range(len(groups) - 1, -1, -1):
            position, rows = groups[group_index]
            first = int(position)
            row_count = rows.height
            last = first + row_count - 1
            self.beginInsertRows(QModelIndex(), first, last)
            parts = [self._df.slice(0, first), rows, self._df.slice(first)]
            self._df = pl.concat([part for part in parts if not part.is_empty()], how="vertical", rechunk=False)
            self.endInsertRows()
            if has_timestamp:
                timestamps = rows["TS"].to_numpy()
                valid = ~np.isnan(timestamps)
                final_position = first + int(np.sum(group_counts[:group_index]))
                pending_times.append(timestamps[valid])
                pending_rows.append(np.flatnonzero(valid).astype(np.int64) + final_position)
        if pending_times:
            self._merge_time_index(np.concatenate(pending_times), np.concatenate(pending_rows))

    @staticmethod
    def _shift_indices(indices: set[int], positions: np.ndarray, shifts: np.ndarray) -> set[int]:
        values = np.fromiter(indices, dtype=np.int64)
        if not values.size:
            return set()
        slots = np.searchsorted(positions, values, side="right")
        moved = values + np.where(slots > 0, shifts[np.maximum(slots - 1, 0)], 0)
        return set(moved.tolist())

    @staticmethod
    def _shift_index_mapping(mapping: dict, positions: np.ndarray, shifts: np.ndarray) -> dict:
        keys = np.fromiter(mapping, dtype=np.int64)
        if not keys.size:
            return {}
        slots = np.searchsorted(positions, keys, side="right")
        moved = keys + np.where(slots > 0, shifts[np.maximum(slots - 1, 0)], 0)
        return {int(row): mapping[int(old)] for row, old in zip(moved, keys)}


    def set_decode_context(self, dbc_manager: DbcManagerViewModel | None, enabled: bool):
        self._dbc_manager = dbc_manager
        self._decode_enabled = enabled
        self._refresh_message_names()
        if not enabled:
            self._expanded_rows.clear()
        self._decode_cache.clear()
        self._decode_cache_by_key.clear()
        self.layoutChanged.emit()

    def set_data_display_mode(self, mode: str):
        normalized = str(mode).strip().lower()
        if normalized not in {"hex", "dec", "bits"}:
            normalized = "hex"
        if self._data_display_mode == normalized:
            return
        self._data_display_mode = normalized
        self.layoutChanged.emit()

    def set_one_row_per_id_view(self, enabled: bool) -> None:
        self._preserve_sort_once = True
        self._one_row_per_id_view = bool(enabled)

    def data_display_mode(self) -> str:
        return self._data_display_mode

    def is_data_bits_display(self) -> bool:
        return self._data_display_mode == "bits"

    def set_all_expanded(self, expanded: bool):
        if expanded:
            self._expanded_rows = set(range(self._df.height))
        else:
            self._expanded_rows.clear()
        self._decode_cache.clear()
        self._decode_cache_by_key.clear()
        self.layoutChanged.emit()

    def toggle_row_expanded(self, row: int):
        if row in self._expanded_rows:
            self._expanded_rows.remove(row)
        else:
            self._expanded_rows.add(row)
        self._decode_cache.pop(row, None)

    def rowCount(self, parent=QModelIndex()):
        return self._df.height

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        col_name = self._columns[index.column()]

        if role == Qt.TextAlignmentRole:
            if col_name == "DATA":
                return int(Qt.AlignLeft | Qt.AlignTop)
            return int(Qt.AlignLeft | Qt.AlignVCenter)

        if role == Qt.FontRole and col_name == "DATA":
            return self._fixed_font

        if role == Qt.ForegroundRole and self._row_foreground is not None:
            return self._row_foreground(index.row())

        if role == Qt.BackgroundRole and self._row_background is not None:
            return self._row_background(index.row())

        if role != Qt.DisplayRole:
            return None

        if col_name == "DATA":
            value = self._df[index.row(), index.column()]
            data_text = format_data_bytes("" if value is None else str(value), mode=self._data_display_mode)
            if self._decode_enabled and self.is_row_expanded(index.row()):
                decode_text = self._get_decode_text(index.row())
                if decode_text:
                    return f"{data_text}\n{decode_text}"
            return data_text

        if col_name == "Name":
            value = self._df[index.row(), index.column()]
            return "" if value is None else str(value)

        if col_name == "ID":
            value = self._df[index.row(), index.column()]
            return "" if value is None else format_can_id(value)

        if col_name in {"PGN", "SA", "DA", "Priority", "PGN Name"}:
            value = self._df[index.row(), index.column()]
            if col_name == "PGN" and value is not None:
                return J1939.format_pgn(int(value))
            if col_name in {"SA", "DA"} and value is not None:
                return f"0x{int(value):02X}"
            return "" if value is None else str(value)

        if col_name == "Delta T":
            value = self._df[index.row(), index.column()]
            if value is None:
                return ""
            return f"{float(value):.6f}".rstrip("0").rstrip(".")

        value = self._df[index.row(), index.column()]
        return "" if value is None else str(value)


    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None

        return (
            self._columns[section]
            if orientation == Qt.Horizontal
            else str(section)
        )

    def sort(self, column: int, order: Qt.SortOrder):
        if column < 0:
            self._sort_column = None
            self._sort_is_applied = False
            natural = self._natural_df
            if natural is not None and not natural.is_empty() and natural.height == self._df.height:
                self.layoutAboutToBeChanged.emit()
                self._df = natural
                self.layoutChanged.emit()
                self._rebuild_time_index()
            return
        self._sort_column = column
        self._sort_descending = order == Qt.DescendingOrder
        if self._df.is_empty():
            self._sort_is_applied = True
            return

        self.layoutAboutToBeChanged.emit()
        self._df = self._apply_active_sort(self._df)
        self._sort_is_applied = True
        self.layoutChanged.emit()
        self._rebuild_time_index()

    def _apply_active_sort(self, df: pl.DataFrame) -> pl.DataFrame:
        if self._sort_column is None or df.is_empty():
            return df
        col = self._columns[self._sort_column]
        if col == "Name" and "ID" in df.columns:
            sort_column = "__trace_name_sort"
            names = {
                str(can_id): self._resolve_message_name(can_id)
                for can_id in df["ID"].unique().to_list()
                if can_id is not None
            }
            values = [names.get(str(can_id)) if can_id is not None else None for can_id in df["ID"].to_list()]
            return (
                df.with_columns(pl.Series(sort_column, values, dtype=pl.String))
                .sort(sort_column, descending=self._sort_descending, maintain_order=True)
                .drop(sort_column)
            )
        if col == "ID":
            sort_column = "__trace_numeric_id_sort"
            values = [can_id_to_int_or_none(value) for value in df[col].to_list()]
            return (
                df.with_columns(pl.Series(sort_column, values, dtype=pl.Int64))
                .sort(sort_column, descending=self._sort_descending, maintain_order=True, nulls_last=True)
                .drop(sort_column)
            )
        if col not in df.columns:
            return df
        return df.sort(col, descending=self._sort_descending, maintain_order=True)

    def get_decode_items(self, row: int) -> list[dict]:
        _, items, _, _ = self._get_decode_cached(row)
        return items

    def get_decode_line_count(self, row: int) -> int:
        if not self.is_row_expanded(row):
            return 0
        _, _, _, line_map = self._get_decode_cached(row)
        return len(line_map)

    def is_decode_enabled(self) -> bool:
        return self._decode_enabled

    def is_row_expanded(self, row: int) -> bool:
        return row in self._expanded_rows

    def _get_decode_text(self, row: int) -> str:
        _, _, text, _ = self._get_decode_cached(row)
        return text

    def get_decode_item_for_line(self, row: int, line_index: int) -> dict | None:
        _, items, _, line_map = self._get_decode_cached(row)
        if line_index < 0 or line_index >= len(line_map):
            return None
        item_index = line_map[line_index]
        if item_index is None:
            return None
        if item_index < 0 or item_index >= len(items):
            return None
        return items[item_index]

    def get_row_can_id(self, row: int) -> str | None:
        if row < 0 or row >= self._df.height:
            return None
        return self._df[row, self._columns.index("ID")]

    def get_row_record(self, row: int) -> dict | None:
        if row < 0 or row >= self._df.height:
            return None
        try:
            return self._df.row(row, named=True)
        except Exception:
            return None

    def _append_time_index(self, dataframe: pl.DataFrame, first_row: int) -> None:
        if "TS" not in dataframe.columns:
            return
        timestamps = dataframe["TS"].to_numpy()
        valid = ~np.isnan(timestamps)
        if not valid.any():
            return
        self._merge_time_index(timestamps[valid], np.flatnonzero(valid).astype(np.int64) + first_row)

    def _merge_time_index(self, pending_times: np.ndarray, pending_rows: np.ndarray) -> None:
        if pending_times.size == 0:
            return
        order = np.argsort(pending_times, kind="stable")
        pending_times = pending_times[order]
        pending_rows = pending_rows[order]
        count = self._time_index_count
        if count == 0 or pending_times[0] >= self._time_index_times[count - 1]:
            new_count = count + pending_times.size
            if new_count > self._time_index_times.size:
                capacity = max(new_count, max(16, self._time_index_times.size * 2))
                self._time_index_times = np.resize(self._time_index_times, capacity)
                self._time_index_rows = np.resize(self._time_index_rows, capacity)
            self._time_index_times[count:new_count] = pending_times
            self._time_index_rows[count:new_count] = pending_rows
            self._time_index_count = new_count
            return
        times = np.concatenate((self._time_index_times[:count], pending_times))
        rows = np.concatenate((self._time_index_rows[:count], pending_rows))
        merged = np.argsort(times, kind="stable")
        self._time_index_times = times[merged]
        self._time_index_rows = rows[merged]
        self._time_index_count = times.size

    def _rebuild_time_index(self) -> None:
        if "TS" not in self._columns or self._df.is_empty():
            self._time_index_times = np.empty(0, dtype=np.float64)
            self._time_index_rows = np.empty(0, dtype=np.int64)
            self._time_index_count = 0
            return
        timestamps = self._df["TS"].to_numpy()
        valid_rows = np.flatnonzero(~np.isnan(timestamps)).astype(np.int64)
        times = timestamps[valid_rows]
        order = np.argsort(times, kind="stable")
        self._time_index_times = times[order]
        self._time_index_rows = valid_rows[order]
        self._time_index_count = times.size

    def rebuild_timestamp_index(self) -> None:
        """Rebuild the timestamp lookup after a source replacement or filter reset."""
        self._rebuild_time_index()

    def nearest_row_for_timestamp(self, timestamp: float) -> int | None:
        """Find the nearest visible row in O(log n), regardless of active sort."""
        if self._time_index_count == 0:
            return None
        times = self._time_index_times[:self._time_index_count]
        rows = self._time_index_rows[:self._time_index_count]
        pos = bisect_left(times, float(timestamp))
        if pos <= 0:
            selected = 0
        elif pos >= len(times):
            selected = len(times) - 1
        else:
            left, right = times[pos - 1], times[pos]
            selected = pos - 1 if abs(left - timestamp) <= abs(right - timestamp) else pos
        return int(rows[selected])

    def get_data_changed_bytes(self, row: int) -> set[int]:
        if row < 0 or row >= self._df.height or "_ChangedBytes" not in self._columns:
            return set()
        try:
            raw = self._df[row, self._columns.index("_ChangedBytes")]
        except Exception:
            return set()
        text = "" if raw is None else str(raw).strip()
        if not text:
            return set()
        result: set[int] = set()
        for chunk in text.split(","):
            part = chunk.strip()
            if not part:
                continue
            try:
                result.add(int(part))
            except ValueError:
                continue
        return result

    def get_raw_data_hex(self, row: int) -> str:
        if row < 0 or row >= self._df.height or "DATA" not in self._columns:
            return ""
        try:
            raw = self._df[row, self._columns.index("DATA")]
        except Exception:
            return ""
        return "" if raw is None else str(raw)

    def _get_decode_cached(
        self,
        row: int,
    ) -> tuple[tuple, list[dict], str, list[int | None]]:
        if not self._decode_enabled or not self._dbc_manager:
            return ((), [], "", [])
        if not self.is_row_expanded(row):
            return ((), [], "", [])
        if row < 0 or row >= self._df.height:
            return ((), [], "", [])

        record = self._df.row(row, named=True)
        can_id = record.get("ID")
        data_hex = record.get("DATA")
        if not can_id or not data_hex:
            return ((), [], "", [])
        dbc_version = getattr(self._dbc_manager, "version", 0)
        key = (can_id, data_hex, dbc_version)

        cached = self._decode_cache.get(row)
        if cached and cached[0] == key:
            return cached

        shared = self._decode_cache_by_key.get(key)
        if shared:
            items, text, line_map = shared
        else:
            items = self._dbc_manager.decode_frame(can_id, data_hex)
            if not items:
                items = decode_bam_frame(self._df, row, self._dbc_manager)
            text, line_map = build_decode_display_lines(items)
            if len(self._decode_cache_by_key) >= self._decode_cache_limit:
                evict = list(self._decode_cache_by_key)[:self._decode_cache_limit // 2]
                for k in evict:
                    self._decode_cache_by_key.pop(k, None)
            self._decode_cache_by_key[key] = (items, text, line_map)


        cached_value = (key, items, text, line_map)
        self._decode_cache[row] = cached_value
        return cached_value

    def _prepare_full_dataframe(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        if "Delta T" in self._columns and "Delta T" not in dataframe.columns:
            deltas = calculate_delta_t(dataframe)
            dataframe = dataframe.with_columns(pl.Series("Delta T", deltas, dtype=pl.Float64))
            self._last_trace_timestamps.clear()
            if {"ID", "TS"}.issubset(dataframe.columns):
                last_values = dataframe.group_by("ID", maintain_order=True).agg(pl.col("TS").last())
                for can_id, timestamp in last_values.iter_rows():
                    if can_id is not None and timestamp is not None:
                        self._last_trace_timestamps[str(can_id)] = float(timestamp)
        dataframe = self._with_resolved_names(dataframe)
        dataframe = self._with_j1939_columns(dataframe)
        return self._add_typed_missing_columns(dataframe)

    def _prepare_appended_dataframe(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        if "Delta T" in self._columns and "Delta T" not in dataframe.columns:
            deltas, updated_timestamps = calculate_appended_delta_t(dataframe, self._last_trace_timestamps)
            dataframe = dataframe.with_columns(pl.Series("Delta T", deltas, dtype=pl.Float64))
            self._last_trace_timestamps = updated_timestamps
        dataframe = self._with_resolved_names(dataframe)
        dataframe = self._with_j1939_columns(dataframe)
        return self._add_typed_missing_columns(dataframe)

    def _add_typed_missing_columns(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        missing = [column for column in self._columns if column not in dataframe.columns]
        if not missing:
            return dataframe
        null_dtypes = {
            "Delta T": pl.Float64,
            "Name": pl.String,
            "PGN": pl.UInt32,
            "SA": pl.UInt32,
            "DA": pl.UInt32,
            "Priority": pl.Int64,
            "PGN Name": pl.String,
        }
        return dataframe.with_columns(
            [pl.lit(None, dtype=null_dtypes.get(column, pl.Null)).alias(column) for column in missing]
        )

    def _resolve_message_name(self, can_id: object) -> str | None:
        if can_id is None or self._dbc_manager is None:
            return None
        key = str(can_id)
        if key not in self._message_names:
            self._message_names[key] = self._dbc_manager.resolve_message_name(key)
        return self._message_names[key]

    def _with_resolved_names(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        if "Name" not in self._columns or "ID" not in dataframe.columns:
            return dataframe
        ids = [can_id for can_id in dataframe["ID"].unique().to_list() if can_id is not None]
        names = {str(can_id): self._resolve_message_name(can_id) for can_id in ids}
        if not names:
            return dataframe.with_columns(pl.lit(None, dtype=pl.String).alias("Name"))
        return dataframe.with_columns(
            pl.col("ID")
            .replace_strict(names, default=None, return_dtype=pl.String)
            .alias("Name")
        )

    def _j1939_values(self, raw_id: object) -> tuple[str | None, str | None, str | None, int | None, str | None]:
        key = str(raw_id or "")
        cached = self._j1939_values_by_id.get(key)
        if cached is not None:
            return cached
        try:
            identifier = J1939.decode_identifier(int(key, 16))
        except (TypeError, ValueError):
            identifier = None
        if identifier is None:
            values = (None, None, None, None, None)
        else:
            name = self._resolve_message_name(key) or pgn_name(identifier.pgn)
            values = (
                J1939.format_pgn(identifier.pgn),
                f"0x{identifier.source_address:02X}",
                None if identifier.destination_address is None else f"0x{identifier.destination_address:02X}",
                identifier.priority,
                name,
            )
        self._j1939_values_by_id[key] = values
        return values

    def _with_j1939_columns(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        columns = self._visible_j1939_columns.intersection(self._columns)
        if not columns or "ID" not in dataframe.columns:
            return dataframe
        raw_id = (
            pl.col("ID")
            .cast(pl.String)
            .str.to_integer(base=16, strict=False)
            .cast(pl.UInt32, strict=False)
        )
        valid = raw_id.is_not_null() & raw_id.is_between(0x800, 0x1FFFFFFF)
        def bits(offset: int, width: int = 1) -> pl.Expr:
            return (raw_id // (1 << offset)) % (1 << width)

        pf = bits(16, 8)
        pgn = (
            bits(25) * (1 << 17)
            + bits(24) * (1 << 16)
            + pf * 256
            + pl.when(pf < 0xF0).then(0).otherwise(bits(8, 8))
        )
        expressions = []
        for column in columns.intersection({"PGN", "SA", "DA", "Priority"}):
            value = {
                "PGN": pgn,
                "SA": bits(0, 8),
                "DA": pl.when(pf < 0xF0).then(bits(8, 8)).otherwise(None),
                "Priority": bits(26, 3),
            }[column]
            expressions.append(pl.when(valid).then(value).otherwise(None).alias(column))
        if "PGN Name" in columns:
            raw_ids = [str(value) for value in dataframe["ID"].unique().to_list() if value is not None]
            names: dict[str, str | None] = {}
            for key in raw_ids:
                values = self._j1939_values(key)
                names[key] = values[4]
            expressions.append(
                pl.col("ID")
                .cast(pl.String)
                .replace_strict(names, default=None, return_dtype=pl.String)
                .alias("PGN Name")
            )
        return dataframe.with_columns(expressions)

    def set_j1939_visible_columns(self, columns: set[str]) -> None:
        visible = {"PGN", "SA", "DA", "Priority", "PGN Name"}.intersection(columns)
        if visible == self._visible_j1939_columns:
            return
        self._visible_j1939_columns = visible
        self._j1939_values_by_id.clear()
        if self._df.is_empty():
            return
        if self.rowCount() and self.columnCount():
            self.layoutAboutToBeChanged.emit()
        self._df = self._prepare_j1939_visibility(self._df)
        if self._natural_df is not None:
            self._natural_df = self._prepare_j1939_visibility(self._natural_df)
        if self._sort_column is not None:
            self._df = self._apply_active_sort(self._df)
            self._sort_is_applied = True
        if self.rowCount() and self.columnCount():
            self._rebuild_time_index()
            self.layoutChanged.emit()
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))

    def _prepare_j1939_visibility(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        dataframe = self._with_j1939_columns(dataframe)
        types = {
            "PGN": pl.UInt32,
            "SA": pl.UInt32,
            "DA": pl.UInt32,
            "Priority": pl.Int64,
            "PGN Name": pl.String,
        }
        hidden = [
            pl.lit(None, dtype=dtype).alias(column)
            for column, dtype in types.items()
            if column not in self._visible_j1939_columns and column in dataframe.columns
        ]
        return dataframe.with_columns(hidden) if hidden else dataframe

    def _refresh_message_names(self) -> None:
        self._message_names.clear()
        self._j1939_values_by_id.clear()
        if "ID" not in self._columns or self._df.is_empty():
            return
        self._df = self._with_resolved_names(self._df)
        self._df = self._with_j1939_columns(self._df)
        if self._natural_df is not None:
            self._natural_df = self._with_resolved_names(self._natural_df)
            self._natural_df = self._with_j1939_columns(self._natural_df)
        name_columns = {"Name", "PGN Name"}
        if self._sort_column is not None and self._columns[self._sort_column] in name_columns:
            self.layoutAboutToBeChanged.emit()
            self._df = self._apply_active_sort(self._df)
            self.layoutChanged.emit()
            self._rebuild_time_index()
        else:
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))


def _same_row_identity(old_df: pl.DataFrame, new_df: pl.DataFrame, count: int) -> bool:
    if count <= 0:
        return True
    keys = [c for c in ("ID", "LEN") if c in old_df.columns and c in new_df.columns]
    if not keys:
        return False
    try:
        old_slice = old_df.slice(0, count).select(keys)
        new_slice = new_df.slice(0, count).select(keys)
        return old_slice.equals(new_slice)
    except Exception:
        return False
