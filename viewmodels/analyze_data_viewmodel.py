from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from models.mux_config import MuxConfigEntry
from services.analyze_data import (
    AnalyzeDataAccumulator,
    ByteSeries,
    build_accumulator,
    detect_mux_cases,
    mux_label_expr,
    sorted_can_ids,
)


class AnalyzeDataViewModel(QObject):
    can_ids_changed = QtSignal(list)
    mux_cases_changed = QtSignal(list)
    summary_changed = QtSignal(dict)
    plot_changed = QtSignal(object)
    selected_id_changed = QtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._df = pl.DataFrame()
        self._selected_id: str | None = None
        self._selected_bytes: set[int] = set(range(8))
        self._mux_configs: list[MuxConfigEntry] = []
        self._selected_mux_case = "All"
        self._ts_min: float | None = None
        self._ts_max: float | None = None
        # Incremental state -- see ingest_raw_chunk()'s docstring for why a
        # full recompute-on-every-batch was the performance problem, and why
        # this is fed from the raw pre-merge chunk instead of diffing self._df.
        self._accumulator = AnalyzeDataAccumulator()
        self._watermark_height = 0
        self._seen_mux_labels: list[str] = []

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @property
    def mux_configs(self) -> list[MuxConfigEntry]:
        return list(self._mux_configs)

    def reset_dataframe(self, df: pl.DataFrame | None) -> None:
        """Wired to data_vm.dataframe_replaced -- the dataframe was swapped
        wholesale (new/reloaded log), not appended to. Drop the incremental
        state so it isn't folded against a now-irrelevant dataset; the
        dataframe_changed emission that always follows dataframe_replaced
        (see LogDataViewModel) triggers the actual full recompute."""
        self._df = df if df is not None else pl.DataFrame()
        self._accumulator = AnalyzeDataAccumulator()
        self._watermark_height = 0
        self._seen_mux_labels = []

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        self._df = df if df is not None else pl.DataFrame()
        ids = sorted_can_ids(self._df)
        self.can_ids_changed.emit(ids)
        id_changed = False
        if self._selected_id not in ids:
            self._selected_id = ids[0] if ids else None
            self.selected_id_changed.emit(self._selected_id or "")
            id_changed = True

        # A live-streaming batch already reached us (and was folded into the
        # running accumulator) via ingest_raw_chunk() -- height matching the
        # watermark means there's nothing left to do here. A mismatch means
        # this growth came from a source ingest_raw_chunk() doesn't see (a
        # loaded/appended log file, a replayed dataframe swap, etc.), so fall
        # back to a full recompute -- safe, and rare enough to not matter.
        if id_changed or self._df.height != self._watermark_height:
            self._full_refresh()

    def set_selected_id(self, can_id: str | None) -> None:
        can_id = (can_id or "").strip().upper() or None
        if self._selected_id == can_id:
            return
        self._selected_id = can_id
        self.selected_id_changed.emit(self._selected_id or "")
        self._selected_mux_case = "All"
        self._full_refresh()

    def set_selected_bytes(self, indexes: set[int]) -> None:
        self._selected_bytes = set(sorted(i for i in indexes if 0 <= i <= 7))
        # Byte selection only picks which already-accumulated series to plot
        # -- it doesn't change which rows matter, so no rescan is needed.
        self.plot_changed.emit(self._accumulator.plot_series(self._selected_bytes))

    def set_mux_configuration(self, configs: list[MuxConfigEntry]) -> None:
        self._mux_configs = list(configs)
        self._selected_mux_case = "All"
        self._full_refresh()

    def set_selected_mux_case(self, case_label: str) -> None:
        new_case = (case_label or "All").strip() or "All"
        if new_case == self._selected_mux_case:
            return
        self._selected_mux_case = new_case
        self._full_refresh()

    def set_time_range(self, ts_min: float | None, ts_max: float | None) -> None:
        self._ts_min = ts_min
        self._ts_max = ts_max
        self._full_refresh()

    def ingest_raw_chunk(self, df_new: pl.DataFrame) -> None:
        """Incremental path -- fed by ConnectionStreamViewModel.chunk_ready
        with the RAW pre-merge chunk, not the merged accumulated dataframe.

        A row-count watermark against the merged dataframe (self._df) would
        be unsafe: merge_frames() (services/log_data.py) re-sorts the WHOLE
        dataframe by TS whenever a chunk arrives slightly out of order
        (routine with live streaming/multi-bus jitter), which can shift
        already-seen rows to a position at/after any index-based watermark.
        Reading the untouched, pre-merge chunk directly sidesteps that
        entirely -- same reasoning as SignalCoverageViewModel.ingest_df.
        """
        if df_new is None or df_new.is_empty():
            return
        self._watermark_height += df_new.height
        if not self._selected_id:
            return
        id_ts_filtered = self._filter_rows(df_new)
        if id_ts_filtered.is_empty():
            return
        mux_bytes = self._mux_bytes_for_selected_id()
        self._update_seen_mux_labels(id_ts_filtered, mux_bytes)
        case_filtered = self._apply_mux_case(id_ts_filtered, mux_bytes)
        if case_filtered.is_empty():
            return
        self._accumulator.feed(case_filtered)
        self.summary_changed.emit(
            self._accumulator.snapshot(self._selected_id, mux_bytes, self._selected_mux_case)
        )
        self.plot_changed.emit(self._accumulator.plot_series(self._selected_bytes))

    def _full_refresh(self) -> None:
        filtered = self._filter_rows(self._df)
        mux_bytes = self._mux_bytes_for_selected_id()
        mux_cases = ["All"] + detect_mux_cases(filtered, mux_bytes)
        self._seen_mux_labels = list(mux_cases[1:])
        if self._selected_mux_case not in mux_cases:
            self._selected_mux_case = "All"
        self.mux_cases_changed.emit(mux_cases)

        active = self._apply_mux_case(filtered, mux_bytes)
        self._accumulator = build_accumulator(active)
        self._watermark_height = self._df.height
        self.summary_changed.emit(
            self._accumulator.snapshot(self._selected_id, mux_bytes, self._selected_mux_case)
        )
        self.plot_changed.emit(self._accumulator.plot_series(self._selected_bytes))

    def _filter_rows(self, df: pl.DataFrame) -> pl.DataFrame:
        if df is None or df.is_empty() or not self._selected_id or "ID" not in df.columns:
            return pl.DataFrame()
        predicate = pl.col("ID") == self._selected_id
        if "TS" in df.columns:
            if self._ts_min is not None:
                predicate = predicate & (pl.col("TS") >= float(self._ts_min))
            if self._ts_max is not None:
                predicate = predicate & (pl.col("TS") <= float(self._ts_max))
        return df.filter(predicate)

    def _apply_mux_case(self, df: pl.DataFrame, mux_bytes: tuple[int, ...]) -> pl.DataFrame:
        if df.is_empty() or not mux_bytes or self._selected_mux_case == "All":
            return df
        return df.filter(mux_label_expr(mux_bytes) == self._selected_mux_case)

    def _mux_bytes_for_selected_id(self) -> tuple[int, ...]:
        can_id = (self._selected_id or "").upper()
        for cfg in self._mux_configs:
            if cfg.can_id == can_id and cfg.length is None:
                return cfg.mux_bytes
        for cfg in self._mux_configs:
            if cfg.can_id == can_id:
                return cfg.mux_bytes
        return ()

    def _update_seen_mux_labels(self, id_ts_filtered_new_rows: pl.DataFrame, mux_bytes: tuple[int, ...]) -> None:
        if not mux_bytes:
            return
        new_labels = detect_mux_cases(id_ts_filtered_new_rows, mux_bytes)
        added = [label for label in new_labels if label not in self._seen_mux_labels]
        if added:
            self._seen_mux_labels.extend(added)
            self.mux_cases_changed.emit(["All"] + self._seen_mux_labels)
