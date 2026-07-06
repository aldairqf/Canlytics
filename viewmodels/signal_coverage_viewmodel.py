from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.signal_coverage import SignalCoverageItem
from viewmodels.signal_coverage_worker import SignalCoverageWorker


class SignalCoverageViewModel(QObject):
    analysis_started = QtSignal()
    analysis_finished = QtSignal()
    analysis_failed = QtSignal(str)
    analysis_canceled = QtSignal()
    results_changed = QtSignal(object)
    progress_changed = QtSignal(int, int)

    def __init__(self, dbc_manager, parent: QObject | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._df = pl.DataFrame()
        self._thread: QThread | None = None
        self._worker: SignalCoverageWorker | None = None
        self._results: list[SignalCoverageItem] = []

    @property
    def results(self) -> list[SignalCoverageItem]:
        return list(self._results)

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        self._df = df if df is not None else pl.DataFrame()

    def start_analysis(self) -> None:
        if self.running:
            return

        self.analysis_started.emit()

        self._thread = QThread(self)
        self._worker = SignalCoverageWorker(
            df=self._df,
            dbc_manager=self._dbc_manager,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.canceled.connect(self._on_canceled)
        self._worker.failed.connect(self._on_failed)
        self._worker.progress.connect(self.progress_changed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.canceled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def cancel_analysis(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.cancel_analysis()
            self._thread.quit()
            self._thread.wait(2000)

    def _on_finished(self, items: list[SignalCoverageItem]) -> None:
        self._results = items
        self.results_changed.emit(items)
        self.analysis_finished.emit()

    def _on_canceled(self) -> None:
        self.analysis_canceled.emit()
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
