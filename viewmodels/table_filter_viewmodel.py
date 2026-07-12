from __future__ import annotations

from PySide6.QtCore import QObject, Signal as QtSignal
import polars as pl

from services.table_filter import IncrementalTableFilter, apply_time_range


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
        # _live_df updates rows in place, so it keeps the full-refilter path below.
        self._history_filter = IncrementalTableFilter()

    def set_history_dataframe(self, df: pl.DataFrame):
        self._history_df = df
        self._emit_filtered()

    def set_live_dataframe(self, df: pl.DataFrame):
        self._live_df = df
        self._emit_filtered()

    def set_real_time_analysis(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._real_time_analysis:
            return
        self._real_time_analysis = enabled
        self._history_filter.reset()
        self._last_ids_emitted = ()
        self._emit_filtered()

    def set_selected_ids(self, ids: set[str]):
        ids = set(ids)
        if ids == self._selected_ids:
            return
        self._selected_ids = ids
        self._history_filter.reset()
        self._last_ids_emitted = ()
        self._emit_filtered()

    def set_time_range(self, ts_min: float | None, ts_max: float | None):
        if ts_min == self._ts_min and ts_max == self._ts_max:
            return
        self._ts_min = ts_min
        self._ts_max = ts_max
        self._history_filter.reset()
        self._last_ids_emitted = ()
        self._emit_filtered()

    def _emit_filtered(self):
        if self._real_time_analysis:
            self._emit_filtered_live()
        else:
            self._emit_filtered_history()

    def _emit_filtered_live(self):
        source = self._live_df
        if source is None:
            return
        source = apply_time_range(source, self._ts_min, self._ts_max)
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

    def _emit_filtered_history(self):
        source = self._history_df
        if source is None:
            return
        filtered, ids, ids_changed = self._history_filter.apply(
            source,
            selected_ids=self._selected_ids,
            ts_min=self._ts_min,
            ts_max=self._ts_max,
        )
        if ids_changed:
            self._last_ids_emitted = tuple(ids)
            self.can_ids_changed.emit(ids)
        self.dataframe_changed.emit(filtered)

    @staticmethod
    def _extract_ids(df: pl.DataFrame) -> list[str]:
        if df is None or df.is_empty() or "ID" not in df.columns:
            return []
        return sorted(df["ID"].unique().to_list())
