from __future__ import annotations

from typing import Callable

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from services.analyze_data import AnalyzeDataPrecomputeCanceled, build_all_accumulators


class AnalyzeDataPrecomputeWorker(QObject):
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(self, *, df: pl.DataFrame, can_ids: list[str], mux_bytes_for_id: Callable[[str], tuple[int, ...]]):
        super().__init__()
        self._df = df
        self._can_ids = can_ids
        self._mux_bytes_for_id = mux_bytes_for_id
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            result = build_all_accumulators(
                self._df,
                self._can_ids,
                self._mux_bytes_for_id,
                should_cancel=lambda: self._cancel_requested,
                on_progress=self.progress.emit,
            )
        except AnalyzeDataPrecomputeCanceled:
            self.canceled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        if self._cancel_requested:
            self.canceled.emit()
            return
        self.finished.emit(result)
