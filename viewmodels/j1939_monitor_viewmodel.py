from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal as QtSignal, Slot

from models.j1939 import J1939AnalysisSnapshot
from services.j1939_analysis import analyze_j1939_dataframe
from utils.timezone_format import format_timestamp


class _J1939MonitorWorker(QObject):
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(self, dataframe: pl.DataFrame | None) -> None:
        super().__init__()
        self._dataframe = dataframe if dataframe is not None else pl.DataFrame()
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        try:
            snapshot = analyze_j1939_dataframe(
                self._dataframe,
                should_cancel=lambda: self._cancel_requested,
                on_progress=self.progress.emit,
            )
        except InterruptedError:
            self.canceled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(snapshot)


class J1939MonitorViewModel(QObject):
    analysis_started = QtSignal()
    analysis_progress = QtSignal(int, int)
    analysis_finished = QtSignal(object)
    analysis_canceled = QtSignal()
    analysis_failed = QtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _J1939MonitorWorker | None = None
        self._snapshot = J1939AnalysisSnapshot((), ())
        self._dataframe = pl.DataFrame()
        self._reanalyze_pending = False
        self._closed = False

    @property
    def snapshot(self) -> J1939AnalysisSnapshot:
        return self._snapshot

    @property
    def analysis_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def set_dataframe(self, dataframe: pl.DataFrame | None) -> None:
        self._dataframe = dataframe if dataframe is not None else pl.DataFrame()

    def clear_snapshot(self) -> None:
        self._snapshot = J1939AnalysisSnapshot((), ())

    def release(self) -> None:
        self.cancel()
        self._dataframe = pl.DataFrame()
        self.clear_snapshot()
        self._reanalyze_pending = False

    def format_timestamp(self, timestamp: float) -> str:
        parent = self.parent()
        mode = getattr(parent, "timezone_mode", "none")
        return format_timestamp(timestamp, mode)

    def analyze(self, dataframe: pl.DataFrame | None = None) -> None:
        if self._closed:
            return
        if self.analysis_running:
            self._reanalyze_pending = True
            if dataframe is not None:
                self._dataframe = dataframe
            return
        if self._thread is not None:
            self._cleanup()
        if dataframe is not None:
            self.set_dataframe(dataframe)
        self.analysis_started.emit()
        self._thread = QThread(self)
        self._worker = _J1939MonitorWorker(self._dataframe)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.canceled.connect(self.analysis_canceled)
        self._worker.failed.connect(self.analysis_failed)
        self._worker.progress.connect(self.analysis_progress)
        self._worker.finished.connect(self._thread.quit)
        self._worker.canceled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        self._thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self) -> None:
        self._closed = True
        self._reanalyze_pending = False
        self._dataframe = pl.DataFrame()
        if self._thread is None:
            return
        self.cancel()
        self._thread.quit()
        stopped = self._thread.wait(2000)
        if not stopped:
            stopped = self._thread.wait()
        if stopped:
            self._cleanup()

    @Slot(object)
    def _on_finished(self, snapshot: J1939AnalysisSnapshot) -> None:
        self._snapshot = snapshot
        self.analysis_finished.emit(snapshot)

    @Slot()
    def _cleanup(self) -> None:
        sender = self.sender()
        if sender is not None and sender is not self._thread:
            return
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        if self._closed:
            self._reanalyze_pending = False
        elif self._reanalyze_pending:
            self._reanalyze_pending = False
            QTimer.singleShot(0, self.analyze)
