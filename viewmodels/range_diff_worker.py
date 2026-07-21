from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from services.range_diff import RangeDiffCanceled, TimeRange, build_range_diff_report


class RangeDiffWorker(QObject):
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(self, *, df: pl.DataFrame, range_a: TimeRange, range_b: TimeRange, dbc_manager):
        super().__init__()
        self._df = df
        self._range_a = range_a
        self._range_b = range_b
        self._dbc_manager = dbc_manager
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            report = build_range_diff_report(
                self._df,
                self._range_a,
                self._range_b,
                dbc_manager=self._dbc_manager,
                should_cancel=lambda: self._cancel_requested,
                on_progress=self.progress.emit,
            )
        except RangeDiffCanceled:
            self.canceled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        if self._cancel_requested:
            self.canceled.emit()
            return
        self.finished.emit(report)
