from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
import polars as pl

class TableModel(QAbstractTableModel):
    def __init__(self, columns: list[str]):
        super().__init__()
        self._columns = columns
        self._df = pl.DataFrame({c: [] for c in columns})
        self._decode_enabled = False
        self._expanded_rows: set[int] = set()
        self._dbc_manager = None
        self._decode_cache: dict[
            int, tuple[tuple, list[dict], str, list[int | None]]
        ] = {}
        self._decode_cache_by_key: dict[
            tuple, tuple[list[dict], str, list[int | None]]
        ] = {}
        self._decode_cache_limit = 2000

    def set_dataframe(self, df: pl.DataFrame):
        self.beginResetModel()
        if df is not None:
            available = [c for c in self._columns if c in df.columns]
            selected = df.select(available)
            for col in self._columns:
                if col not in selected.columns:
                    selected = selected.with_columns(pl.lit(None).alias(col))
            self._df = selected.select(self._columns)
        else:
            self._df = self._df.clear()
        self._decode_cache.clear()
        self.endResetModel()

    def set_decode_context(self, dbc_manager, enabled: bool):
        self._dbc_manager = dbc_manager
        self._decode_enabled = enabled
        if not enabled:
            self._expanded_rows.clear()
        self._decode_cache.clear()
        self._decode_cache_by_key.clear()
        self.layoutChanged.emit()

    def set_all_expanded(self, expanded: bool):
        if expanded:
            self._expanded_rows = set(range(self._df.height))
        else:
            self._expanded_rows.clear()
        self._decode_cache.clear()
        self._decode_cache_by_key.clear()
        self.layoutChanged.emit()

    def toggle_row_expanded(self, row: int):
        if row not in self._expanded_rows:
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

        if role != Qt.DisplayRole:
            return None

        if col_name == "DATA":
            value = self._df[index.row(), index.column()]
            data_text = "" if value is None else str(value)
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
            lines = []
            line_map = []
            for idx, item in enumerate(items):
                unit = item.get("unit")
                suffix = f" {unit}" if unit else ""
                lines.append(f"{item['name']}: {item['value']}{suffix}")
                line_map.append(idx)
            text = "\n".join(lines)
            if len(self._decode_cache_by_key) >= self._decode_cache_limit:
                self._decode_cache_by_key.clear()
            self._decode_cache_by_key[key] = (items, text, line_map)


        cached_value = (key, items, text, line_map)
        self._decode_cache[row] = cached_value
        return cached_value
