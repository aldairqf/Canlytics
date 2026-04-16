from __future__ import annotations

from typing import Optional

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from viewmodels.log_loader_worker import LogLoaderWorker


class LogLoadViewModel(QObject):

    load_started = QtSignal(str)  # path
    loaded = QtSignal(str, pl.DataFrame, bool, object)  # path, df, is_full_load, source_tz_offset_minutes
    load_failed = QtSignal(str)  # message
    load_canceled = QtSignal()
    load_finished = QtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[LogLoaderWorker] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(
        self,
        *,
        path: str,
        normalize: bool,
        mode: str,
        source_tz_offset_minutes: int | None = None,
    ) -> None:
        if self.running:
            return

        self.load_started.emit(path)

        self._thread = QThread()
        self._worker = LogLoaderWorker(path, normalize, mode, source_tz_offset_minutes)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_loaded)
        self._worker.canceled.connect(self._on_canceled)
        self._worker.failed.connect(self._on_failed)

        self._worker.finished.connect(self._thread.quit)
        self._worker.canceled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)

        self._thread.start()

    def cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            if self._worker is not None:
                self._worker.cancel()
            self._thread.quit()
            self._thread.wait(2000)

    def _on_loaded(self, path: str, df: pl.DataFrame, is_full_load: bool, source_tz_offset_minutes: object) -> None:
        if self._worker and getattr(self._worker, "cancel_requested", False):
            return
        self.loaded.emit(path, df, is_full_load, source_tz_offset_minutes)
        self.load_finished.emit()

    def _on_canceled(self) -> None:
        self.load_canceled.emit()
        self.load_finished.emit()

    def _on_failed(self, message: str) -> None:
        self.load_failed.emit(message)
        self.load_finished.emit()

    def _cleanup(self) -> None:
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
