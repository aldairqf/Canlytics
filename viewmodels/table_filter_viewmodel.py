from PySide6.QtCore import QObject, Signal
import polars as pl


class TableFilterViewModel(QObject):
    dataframe_changed = Signal(object)
    can_ids_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self._history_df: pl.DataFrame | None = None
        self._live_df: pl.DataFrame | None = None
        self._selected_ids: set[str] = set()
        self._real_time_analysis = False

    def set_history_dataframe(self, df: pl.DataFrame):
        self._history_df = df
        self._emit_filtered()

    def set_live_dataframe(self, df: pl.DataFrame):
        self._live_df = df
        self._emit_filtered()

    def set_real_time_analysis(self, enabled: bool):
        self._real_time_analysis = bool(enabled)
        self._emit_filtered()

    def set_selected_ids(self, ids: set[str]):
        ids = set(ids)
        if ids == self._selected_ids:
            return
        self._selected_ids = ids
        self._emit_filtered()

    def _emit_filtered(self):
        source = self._live_df if self._real_time_analysis else self._history_df
        if source is None:
            return

        self.can_ids_changed.emit(self._extract_ids(source))

        if "ID" not in source.columns:
            self.dataframe_changed.emit(source.head(0))
            return

        if not self._selected_ids:
            df = source.head(0)
        else:
            df = source.filter(pl.col("ID").is_in(self._selected_ids))

        self.dataframe_changed.emit(df)

    @staticmethod
    def _extract_ids(df: pl.DataFrame) -> list[str]:
        if df is None or df.is_empty() or "ID" not in df.columns:
            return []
        return sorted(df["ID"].unique().to_list())
