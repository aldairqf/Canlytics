from __future__ import annotations

from typing import Any
from dataclasses import replace

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.mux_detector import MuxDetectorConfig
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

    def start_analysis(self, *, selected_groups: list[tuple[str, int]], options: dict[str, bool]) -> None:
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
    return sorted(pairs, key=lambda item: (_can_id_sort_key(item[0]), item[1]))


def _can_id_sort_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip().upper()
    try:
        return (0, int(text, 16))
    except ValueError:
        return (1, text)


def _build_config(options: dict[str, bool]) -> MuxDetectorConfig:
    cfg = MuxDetectorConfig(
        enable_bitfields=bool(options.get("enable_bitfields", False)),
        enable_nmi=bool(options.get("use_nmi", True)),
        enable_window_entropy=bool(options.get("use_window_entropy", False)),
        byte_lengths=(1, 2, 3, 4),
        max_candidates_per_len=20,
    )
    updates: dict[str, object] = {}
    strictness = max(0, min(int(options.get("strictness", 50)), 100)) / 100.0

    updates["min_change_rate"] = 0.001 + (0.029 * strictness)
    updates["max_unique_ratio"] = 0.8 - (0.45 * strictness)
    updates["period_mean_median_rel_max"] = 0.5 - (0.25 * strictness)
    updates["period_cv_max"] = 1.0 - (0.7 * strictness)
    updates["max_unaccepted_percent"] = 0.5 - (0.35 * strictness)
    updates["nmi_threshold"] = 0.15 + (0.25 * strictness)
    updates["sigmoid_bias"] = 2.0 + (1.5 * strictness)
    updates["max_candidates_per_len"] = max(5, int(round(20 - (12 * strictness))))
    updates["top_k_dependent_bytes"] = max(2, int(round(3 - strictness)))

    if not options.get("use_change_rate", True):
        updates["min_change_rate"] = 0.0
        updates["w_change"] = 0.0

    if not options.get("use_unique_ratio", True):
        updates["max_unique_ratio"] = 1.0
        updates["p_too_many_unique"] = 0.0
        updates["w_diversity"] = 0.0

    if not options.get("use_periodicity", True):
        updates["w_period_factor"] = 0.0
        updates["w_regularity"] = 0.0
        updates["p_unaccepted"] = 0.0

    if not options.get("use_nmi", True):
        updates["w_nmi_mean"] = 0.0
        updates["w_nmi_peak"] = 0.0
        updates["w_nmi_fraction"] = 0.0

    if not options.get("use_entropy", False):
        updates["w_entropy"] = 0.0

    if options.get("require_early_state_presence", False):
        updates["require_early_state_presence"] = True
        updates["early_state_presence_threshold"] = 0.15
        updates["max_late_state_fraction"] = 0.25

    return replace(cfg, **updates) if updates else cfg
