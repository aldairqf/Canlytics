from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Iterable

import polars as pl
from PySide6.QtCore import QObject, QThread, Qt, Signal as QtSignal, Slot

from services.log_export import ExportCancelled, export_dataframe, select_export_frames


class _LogExportWorker(QObject):
    progress = QtSignal(int, int)
    succeeded = QtSignal(str)
    failed = QtSignal(str)
    canceled = QtSignal()
    finished = QtSignal()

    def __init__(self, dataframe: pl.DataFrame, path: str, protected_paths: Iterable[str]):
        super().__init__()
        self._dataframe = dataframe
        self._path = path
        self._protected_paths = tuple(protected_paths)
        self._cancel_requested = Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    @Slot()
    def run(self) -> None:
        try:
            path = export_dataframe(
                self._dataframe,
                self._path,
                progress_callback=self.progress.emit,
                should_cancel=self._cancel_requested.is_set,
                protected_paths=self._protected_paths,
            )
        except ExportCancelled:
            self.canceled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(str(path))
        finally:
            self.finished.emit()


class LogExportViewModel(QObject):
    progress_changed = QtSignal(int, int)
    export_succeeded = QtSignal(str)
    export_failed = QtSignal(str)
    export_canceled = QtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _LogExportWorker | None = None
        self.result_path: str | None = None
        self.error_message: str | None = None
        self.was_canceled = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_export(
        self,
        dataframe: pl.DataFrame,
        path: str | Path,
        *,
        protected_paths: Iterable[str] = (),
    ) -> bool:
        if self.running:
            return False
        self.result_path = None
        self.error_message = None
        self.was_canceled = False
        thread = QThread(self)
        worker = _LogExportWorker(dataframe, str(path), protected_paths)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress_changed.emit)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.canceled.connect(self._on_canceled)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup)
        self._thread = thread
        self._worker = worker
        thread.start()
        return True

    def select_frames(
        self,
        dataframe: pl.DataFrame,
        scope: str,
        *,
        selected_ids: Iterable[str] = (),
        ts_min: float | None = None,
        ts_max: float | None = None,
    ) -> pl.DataFrame:
        return select_export_frames(
            dataframe, scope, selected_ids=selected_ids, ts_min=ts_min, ts_max=ts_max
        )

    def wait(self, timeout_ms: int = 50) -> bool:
        return self._thread is None or self._thread.wait(timeout_ms)

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self) -> None:
        self.cancel()
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(2000)

    @Slot(str)
    def _on_succeeded(self, path: str) -> None:
        self.result_path = path
        self.export_succeeded.emit(path)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.error_message = message
        self.export_failed.emit(message)

    @Slot()
    def _on_canceled(self) -> None:
        self.was_canceled = True
        self.export_canceled.emit()

    @Slot()
    def _cleanup(self) -> None:
        thread = self.sender()
        if thread == self._thread:
            self._worker = None
            self._thread = None
        if isinstance(thread, QThread):
            thread.deleteLater()
