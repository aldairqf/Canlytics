from PySide6.QtCore import QObject, Signal
import polars as pl


class TableFilterViewModel(QObject):
    dataframe_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self._df_all: pl.DataFrame | None = None
        self._selected_ids: set[str] = set()

    def set_dataframe(self, df: pl.DataFrame):
        self._df_all = df
        self._emit_filtered()

    def set_selected_ids(self, ids: set[str]):
        self._selected_ids = ids
        self._emit_filtered()

    def _emit_filtered(self):
        if self._df_all is None:
            return

        if "ID" not in self._df_all.columns:
            self.dataframe_changed.emit(self._df_all.head(0))
            return

        if not self._selected_ids:
            df = self._df_all.head(0)
        else:
            df = self._df_all.filter(pl.col("ID").is_in(self._selected_ids))

        self.dataframe_changed.emit(df)
