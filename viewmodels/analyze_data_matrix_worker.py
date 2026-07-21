from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from services.analyze_data import AnalyzeDataPrecomputeCanceled, build_matrix_summary


class AnalyzeDataMatrixWorker(QObject):
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(self, *, df: pl.DataFrame, can_ids: list[str]):
        super().__init__()
        self._df = df
        self._can_ids = can_ids
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            result = build_matrix_summary(
                self._df,
                self._can_ids,
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
