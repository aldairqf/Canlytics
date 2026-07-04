from __future__ import annotations

from typing import Any

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.mux_detector import MuxDetectorConfig, PayloadDecodeConfig
from utils.can_id import can_id_sort_key
from viewmodels.mux_detection_worker import MuxDetectionWorker


class MuxDetectionViewModel(QObject):
    available_signals_changed = QtSignal(list)
    analysis_started = QtSignal()
    analysis_finished = QtSignal()
    analysis_failed = QtSignal(str)
    results_changed = QtSignal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._df = pl.DataFrame()
        self._ts_min: float | None = None
        self._ts_max: float | None = None
        self._thread: QThread | None = None
        self._worker: MuxDetectionWorker | None = None
        self._results: list[dict[str, Any]] = []

    @property
    def results(self) -> list[dict[str, Any]]:
        return list(self._results)

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        self._df = df if df is not None else pl.DataFrame()
        self.available_signals_changed.emit(_grouped_signals(self._effective_df()))

    def set_time_range(self, ts_min: float | None, ts_max: float | None) -> None:
        self._ts_min = ts_min
        self._ts_max = ts_max
        self.available_signals_changed.emit(_grouped_signals(self._effective_df()))

    def start_analysis(self, *, selected_groups: list[tuple[str, int]], options: dict[str, Any]) -> None:
        if self.running or self._df is None:
            return

        self.analysis_started.emit()
        config = _build_config(options)

        self._thread = QThread()
        self._worker = MuxDetectionWorker(
            df=self._effective_df(),
            selected_groups=selected_groups,
            config=config,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    def _on_finished(self, results: list[dict[str, Any]]) -> None:
        self._results = results
        self.results_changed.emit(results)
        self.analysis_finished.emit()

    def _on_failed(self, message: str) -> None:
        self.analysis_failed.emit(message)
        self.analysis_finished.emit()

    def _cleanup(self) -> None:
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None

    def _effective_df(self) -> pl.DataFrame:
        df = self._df if self._df is not None else pl.DataFrame()
        if df.is_empty() or "TS" not in df.columns:
            return df
        if self._ts_min is not None:
            df = df.filter(pl.col("TS") >= float(self._ts_min))
        if self._ts_max is not None:
            df = df.filter(pl.col("TS") <= float(self._ts_max))
        return df


def _grouped_signals(df: pl.DataFrame) -> list[tuple[str, int]]:
    if df is None or df.is_empty() or "ID" not in df.columns or "LEN" not in df.columns:
        return []
    pairs = {
        (str(can_id).upper(), int(frame_len))
        for can_id, frame_len in df.select(["ID", "LEN"]).iter_rows()
        if can_id is not None and frame_len is not None and int(frame_len) > 0
    }
    return sorted(pairs, key=lambda item: (can_id_sort_key(item[0]), item[1]))


def _build_config(options: dict[str, Any]) -> MuxDetectorConfig:
    # Sensitivity is the only derived value: 0 (strict) .. 100 (permissive) maps
    # linearly to the min_nmi acceptance threshold. Every other field below is
    # read directly from the UI with no hidden formula.
    sensitivity = max(0, min(int(options.get("sensitivity", 50)), 100)) / 100.0
    min_nmi = 0.70 - (0.40 * sensitivity)  # 0.70 (strict) .. 0.30 (permissive)
    selected_widths = tuple(int(value) for value in options.get("candidate_widths", (1, 2, 3, 4)))
    payload_cfg = PayloadDecodeConfig(
        enable_int_uint=bool(options.get("decode_int_uint", True)),
        enable_float32=bool(options.get("decode_float32", True)),
        enable_bitfields=bool(options.get("decode_bitfields", False)),
        max_decode_candidates=int(options.get("max_decode_candidates", 12)),
    )
    return MuxDetectorConfig(
        candidate_widths=selected_widths or (1, 2, 3, 4),
        min_support=int(options.get("min_support", 10)),
        max_cardinality=int(options.get("max_cardinality", 32)),
        min_nmi=float(options.get("min_nmi", min_nmi)),
        payload=payload_cfg,
    )
