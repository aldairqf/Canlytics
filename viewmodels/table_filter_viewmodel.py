from __future__ import annotations

from PySide6.QtCore import QObject, Signal as QtSignal
import polars as pl


class TableFilterViewModel(QObject):
    dataframe_changed = QtSignal(object)
    can_ids_changed = QtSignal(list)

    def __init__(self):
        super().__init__()
        self._history_df: pl.DataFrame | None = None
        self._live_df: pl.DataFrame | None = None
        self._selected_ids: set[str] = set()
        self._real_time_analysis = False
        self._ts_min: float | None = None
        self._ts_max: float | None = None
        self._last_ids_emitted: tuple[str, ...] = ()

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

    def set_time_range(self, ts_min: float | None, ts_max: float | None):
        if ts_min == self._ts_min and ts_max == self._ts_max:
            return
        self._ts_min = ts_min
        self._ts_max = ts_max
        self._emit_filtered()

    def _emit_filtered(self):
        source = self._live_df if self._real_time_analysis else self._history_df
        if source is None:
            return

        source = self._apply_time_range(source)
        current_ids = tuple(self._extract_ids(source))
        if current_ids != self._last_ids_emitted:
            self._last_ids_emitted = current_ids
            self.can_ids_changed.emit(list(current_ids))

        if "ID" not in source.columns:
            self.dataframe_changed.emit(source.head(0))
            return

        if not self._selected_ids:
            df = source.head(0)
        else:
            df = source.filter(pl.col("ID").is_in(self._selected_ids))

        self.dataframe_changed.emit(df)

    def _apply_time_range(self, df: pl.DataFrame) -> pl.DataFrame:
        if df is None or df.is_empty() or "TS" not in df.columns:
            return df
        filtered = df
        if self._ts_min is not None:
            filtered = filtered.filter(pl.col("TS") >= float(self._ts_min))
        if self._ts_max is not None:
            filtered = filtered.filter(pl.col("TS") <= float(self._ts_max))
        return filtered

    @staticmethod
    def _extract_ids(df: pl.DataFrame) -> list[str]:
        if df is None or df.is_empty() or "ID" not in df.columns:
            return []
        return sorted(df["ID"].unique().to_list())
