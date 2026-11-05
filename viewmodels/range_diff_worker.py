from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal
from pathlib import Path

from services.can_log import CANLog
from services.range_diff import RangeDiffCanceled, RangeDiffReport, TimeRange, build_range_diff_report, build_source_diff_report


class RangeDiffWorker(QObject):
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(
        self,
        *,
        df: pl.DataFrame,
        range_a: TimeRange,
        range_b: TimeRange,
        dbc_manager,
        source_paths: tuple[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._df = df
        self._range_a = range_a
        self._range_b = range_b
        self._dbc_manager = dbc_manager
        self._source_paths = source_paths
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            if self._source_paths is None:
                report = build_range_diff_report(
                    self._df,
                    self._range_a,
                    self._range_b,
                    dbc_manager=self._dbc_manager,
                    should_cancel=lambda: self._cancel_requested,
                    on_progress=self.progress.emit,
                )
            else:
                report = self._run_source_comparison()
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

    def _run_source_comparison(self) -> RangeDiffReport:
        path_a, path_b = self._source_paths
        bytes_a = max(1, Path(path_a).stat().st_size)
        bytes_b = max(1, Path(path_b).stat().st_size)
        total_bytes = bytes_a + bytes_b
        self.progress.emit(0, 100)
        dataframe_a = CANLog(path_a).load(normalize_time=False)
        if self._cancel_requested:
            raise RangeDiffCanceled()
        self.progress.emit(max(1, int(50 * bytes_a / total_bytes)), 100)
        dataframe_b = CANLog(path_b).load(normalize_time=False)
        if self._cancel_requested:
            raise RangeDiffCanceled()
        self.progress.emit(50, 100)

        def report_progress(done: int, total: int) -> None:
            percent = 50 + int(50 * done / max(1, total))
            self.progress.emit(percent, 100)

        report = build_source_diff_report(
            dataframe_a,
            dataframe_b,
            dbc_manager=self._dbc_manager,
            should_cancel=lambda: self._cancel_requested,
            on_progress=report_progress,
        )
        self.progress.emit(100, 100)
        return report
