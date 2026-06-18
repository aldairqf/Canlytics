from __future__ import annotations

import polars as pl
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PySide6.QtGui import QFontDatabase

from services.bam_decode import decode_bam_frame
from services.dbc_manager import DbcManager

class TableModel(QAbstractTableModel):
    def __init__(self, columns: list[str], *, optimize_append: bool = True):
        super().__init__()
        self._columns = columns
        self._optimize_append = optimize_append
        self._df = pl.DataFrame({c: [] for c in columns})
        self._decode_enabled = False
        self._expanded_rows: set[int] = set()
        self._dbc_manager: DbcManager | None = None
        self._decode_cache: dict[
            int, tuple[tuple, list[dict], str, list[int | None]]
        ] = {}
        self._decode_cache_by_key: dict[
            tuple, tuple[list[dict], str, list[int | None]]
        ] = {}
        self._decode_cache_limit = 2000
        self._fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self._data_display_mode = "bytes"

    def set_dataframe(self, df: pl.DataFrame):
        if df is None:
            self.beginResetModel()
            self._df = self._df.clear()
            self._decode_cache.clear()
            self._decode_cache_by_key.clear()
            self.endResetModel()
            return

        available = [c for c in self._columns if c in df.columns]
        selected = df.select(available)
        for col in self._columns:
            if col not in selected.columns:
                selected = selected.with_columns(pl.lit(None).alias(col))
        new_df = selected.select(self._columns)

        old_h = int(self._df.height)
        new_h = int(new_df.height)

        if old_h == 0 and new_h > 0:
            self.beginInsertRows(QModelIndex(), 0, new_h - 1)
            self._df = new_df
            self.endInsertRows()
            return

        if old_h > 0 and new_h == old_h:
            self._df = new_df
            if new_h > 0 and self.columnCount() > 0:
                top_left = self.index(0, 0)
                bottom_right = self.index(new_h - 1, self.columnCount() - 1)
                self.dataChanged.emit(top_left, bottom_right)
            return

        if self._optimize_append and old_h > 0 and new_h > old_h:
            if _same_row_identity(self._df, new_df, old_h):
                existing_new = new_df.slice(0, old_h)
                tail = new_df.slice(old_h, new_h - old_h)
                self._df = existing_new
                if old_h > 0 and self.columnCount() > 0:
                    self.dataChanged.emit(self.index(0, 0), self.index(old_h - 1, self.columnCount() - 1))
                if tail.height > 0:
                    self.beginInsertRows(QModelIndex(), old_h, new_h - 1)
                    self._df = pl.concat([self._df, tail], how="vertical", rechunk=True)
                    self.endInsertRows()
                return

        self.beginResetModel()
        self._df = new_df
        self._decode_cache.clear()
        self._decode_cache_by_key.clear()
        self.endResetModel()


    def set_decode_context(self, dbc_manager: DbcManager | None, enabled: bool):
        self._dbc_manager = dbc_manager
        self._decode_enabled = enabled
        if not enabled:
            self._expanded_rows.clear()
        self._decode_cache.clear()
        self._decode_cache_by_key.clear()
        self.layoutChanged.emit()

    def set_data_display_mode(self, mode: str):
        normalized = "bits" if str(mode).strip().lower() == "bits" else "bytes"
        if self._data_display_mode == normalized:
            return
        self._data_display_mode = normalized
        self.layoutChanged.emit()

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

        if role != Qt.DisplayRole:
            return None

        if col_name == "DATA":
            value = self._df[index.row(), index.column()]
            data_text = format_data_bytes("" if value is None else str(value), as_bits=self.is_data_bits_display())
            if self._decode_enabled and self.is_row_expanded(index.row()):
                decode_text = self._get_decode_text(index.row())
                if decode_text:
                    return f"{data_text}\n{decode_text}"
            return data_text

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
        if self._df.is_empty():
            return

        self.layoutAboutToBeChanged.emit()
        col = self._columns[column]
        self._df = self._df.sort(col, descending=order == Qt.DescendingOrder)
        self.layoutChanged.emit()

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
            lines = []
            line_map = []
            for idx, item in enumerate(items):
                unit = item.get("unit")
                suffix = f" {unit}" if unit else ""
                lines.append(f"{item['name']}: {item['value']}{suffix}")
                line_map.append(idx)
            text = "\n".join(lines)
            if len(self._decode_cache_by_key) >= self._decode_cache_limit:
                evict = list(self._decode_cache_by_key)[:self._decode_cache_limit // 2]
                for k in evict:
                    self._decode_cache_by_key.pop(k, None)
            self._decode_cache_by_key[key] = (items, text, line_map)


        cached_value = (key, items, text, line_map)
        self._decode_cache[row] = cached_value
        return cached_value


def format_data_bytes(data_hex: str, *, as_bits: bool = False) -> str:
    text = (data_hex or "").strip().upper()
    if not text:
        return ""
    if len(text) % 2 != 0:
        return text
    if as_bits:
        return " ".join(f"{int(text[i : i + 2], 16):08b}" for i in range(0, len(text), 2))
    return " ".join(text[i : i + 2] for i in range(0, len(text), 2))


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
