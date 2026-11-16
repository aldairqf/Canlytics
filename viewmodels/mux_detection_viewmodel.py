from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from config.defaults import (MUX_SENSITIVITY_MAX_VALUES_HIGH, MUX_SENSITIVITY_MAX_VALUES_LOW,
                             MUX_SENSITIVITY_MIN_GAIN_HIGH, MUX_SENSITIVITY_MIN_GAIN_LOW)
from models.mux_config import MuxConfigEntry
from services.mux_detector import MuxDetectorConfig
from viewmodels.mux_detection_worker import MuxDetectionWorker


class MuxDetectionViewModel(QObject):
    analysis_started = QtSignal()
    analysis_finished = QtSignal()
    analysis_failed = QtSignal(str)
    progress_changed = QtSignal(int, int)
    results_changed = QtSignal(object)
    configuration_applied = QtSignal(str, bool)
    configuration_apply_blocked = QtSignal(str)

    def __init__(self, mux_configuration_vm=None, parent: QObject | None = None):
        super().__init__(parent)
        self._mux_configuration_vm = mux_configuration_vm
        self._df = pl.DataFrame()
        self._ts_min: float | None = None
        self._ts_max: float | None = None
        self._thread: QThread | None = None
        self._worker: MuxDetectionWorker | None = None
        self._results: list[dict[str, object]] = []
        self._sensitivity = 50
        self._replacement_id: str | None = None

    @property
    def results(self) -> list[dict[str, object]]:
        return list(self._results)

    @property
    def running(self) -> bool:
        return self._thread is not None

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        self._df = df if df is not None else pl.DataFrame()

    def set_time_range(self, ts_min: float | None, ts_max: float | None) -> None:
        self._ts_min, self._ts_max = ts_min, ts_max

    def start_analysis(self, *, selected_groups=None, options=None) -> None:
        if self.running:
            return
        self._sensitivity = int((options or {}).get("sensitivity", self._sensitivity))
        self._replacement_id = None
        self._start_worker(selected_groups, forced_selector=None)

    def recalculate_selector(self, can_id: str, selector: tuple[int, ...]) -> None:
        if self.running or not selector or len(selector) > 4:
            return
        ordered = tuple(sorted(set(int(byte) for byte in selector)))
        if ordered != tuple(range(ordered[0], ordered[0] + len(ordered))):
            return
        self._replacement_id = str(can_id)
        self._start_worker([str(can_id)], forced_selector=ordered)

    def _start_worker(self, can_ids, *, forced_selector):
        sensitivity = max(0, min(100, self._sensitivity)) / 100
        min_gain = MUX_SENSITIVITY_MIN_GAIN_LOW + sensitivity * (
            MUX_SENSITIVITY_MIN_GAIN_HIGH - MUX_SENSITIVITY_MIN_GAIN_LOW
        )
        max_values = int(round(MUX_SENSITIVITY_MAX_VALUES_LOW + sensitivity * (
            MUX_SENSITIVITY_MAX_VALUES_HIGH - MUX_SENSITIVITY_MAX_VALUES_LOW
        )))
        self._thread = QThread(self)
        self._worker = MuxDetectionWorker(df=self._effective_df(), can_ids=can_ids,
                                          config=MuxDetectorConfig(min_gain=min_gain, max_values=max_values),
                                          forced_selectors=({self._replacement_id: forced_selector}
                                                            if forced_selector is not None else None))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress_changed)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        self.analysis_started.emit()
        self._thread.start()

    def cancel_analysis(self) -> None:
        if self._worker:
            self._worker.cancel()

    def apply_result(self, can_id: str) -> bool:
        result = next((r for r in self._results if r["can_id"] == can_id), None)
        if not result or not result.get("has_mux") or self._mux_configuration_vm is None:
            return False
        if result.get("excluded_values"):
            self.configuration_apply_blocked.emit(str(can_id))
            return False
        entry = MuxConfigEntry(str(can_id), None, tuple(result["selector"]))
        current = self._mux_configuration_vm.configs
        conflict = any(item.can_id == entry.can_id and item.length is None and item.mux_bytes != entry.mux_bytes for item in current)
        updated = [item for item in current if not (item.can_id == entry.can_id and item.length is None)]
        updated.append(entry)
        self._mux_configuration_vm.set_configuration(updated)
        self.configuration_applied.emit(str(can_id), conflict)
        return conflict

    def is_result_applied(self, can_id: str, selector: tuple[int, ...]) -> bool:
        """Return whether the shared MUX configuration already stores this selector."""
        return any(
            entry.can_id == str(can_id)
            and entry.length is None
            and entry.mux_bytes == tuple(selector)
            for entry in getattr(self._mux_configuration_vm, "configs", ())
        )

    def _on_finished(self, results) -> None:
        if self._replacement_id is not None:
            if results:
                previous = next((item for item in self._results
                                 if item["can_id"] == self._replacement_id), None)
                replacement = dict(results[0])
                if previous and previous.get("excluded_values"):
                    valid_values = {value["value"] for value in replacement.get("values", [])}
                    replacement["excluded_values"] = [value for value in previous["excluded_values"]
                                                       if value in valid_values]
                self._results = [item for item in self._results if item["can_id"] != self._replacement_id] + list(results)
                self._results = [replacement if item["can_id"] == self._replacement_id else item
                                 for item in self._results]
                self._results.sort(key=lambda item: str(item["can_id"]))
            self._replacement_id = None
        else:
            self._results = list(results)
        self.results_changed.emit(self._results)
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

    def shutdown(self) -> None:
        self.cancel_analysis()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)

    def _effective_df(self) -> pl.DataFrame:
        df = self._df
        if "TS" in df.columns and self._ts_min is not None:
            df = df.filter(pl.col("TS") >= self._ts_min)
        if "TS" in df.columns and self._ts_max is not None:
            df = df.filter(pl.col("TS") <= self._ts_max)
        return df
