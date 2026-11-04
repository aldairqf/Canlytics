from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.bit_activity import BitActivityAccumulator, BitActivitySnapshot
from services.can_data_parser import empty_frame
from utils.can_id import can_id_sort_key
from viewmodels.bit_activity_worker import BitActivityWorker


class BitActivityViewModel(QObject):
    analysis_started = QtSignal()
    analysis_finished = QtSignal()
    analysis_failed = QtSignal(str)
    analysis_canceled = QtSignal()
    progress_changed = QtSignal(int, int)
    results_changed = QtSignal(object, bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._dataframe = empty_frame()
        self._accumulator = BitActivityAccumulator()
        self._results: dict[str, BitActivitySnapshot] = {}
        self._thread: QThread | None = None
        self._worker: BitActivityWorker | None = None
        self._pending_chunks: list[pl.DataFrame] = []
        self._active = False
        self._ready = False
        self._dirty = True
        self._generation = 0
        self._scan_generation = 0
        self._restart_after_cleanup = False

    @property
    def results(self) -> tuple[BitActivitySnapshot, ...]:
        return tuple(self._results[key] for key in sorted(self._results, key=can_id_sort_key))

    @property
    def running(self) -> bool:
        return self._thread is not None

    def activate(self) -> None:
        self._active = True
        if self._dirty and not self.running:
            self.start_analysis()

    def deactivate(self) -> None:
        self._active = False

    def set_dataframe(self, dataframe: pl.DataFrame | None) -> None:
        self._dataframe = dataframe if dataframe is not None else empty_frame()

    def replace_dataframe(self, dataframe: pl.DataFrame | None) -> None:
        self._dataframe = dataframe if dataframe is not None else empty_frame()
        self._generation += 1
        self._dirty = True
        self._ready = False
        self._pending_chunks.clear()
        self._results.clear()
        self.results_changed.emit((), True)
        if self.running:
            self._restart_after_cleanup = self._active
            if self._worker is not None:
                self._worker.cancel()
        elif self._active:
            self.start_analysis()

    def append_rows(self, dataframe: pl.DataFrame) -> None:
        if dataframe is None or dataframe.is_empty():
            return
        if self.running:
            self._pending_chunks.append(dataframe)
            return
        if not self._ready or self._dirty:
            return
        changed = self._accumulator.ingest(dataframe)
        if not changed:
            return
        for item in changed:
            self._results[item.can_id] = item
        self.results_changed.emit(changed, False)

    def start_analysis(self) -> None:
        if self.running:
            return
        if self._dataframe.is_empty():
            self._accumulator.reset()
            self._results.clear()
            self._ready = True
            self._dirty = False
            self.results_changed.emit((), True)
            self.analysis_started.emit()
            self.analysis_finished.emit()
            return

        self.analysis_started.emit()
        self._pending_chunks.clear()
        self._scan_generation = self._generation
        self._restart_after_cleanup = False
        self._thread = QThread(self)
        self._worker = BitActivityWorker(self._dataframe)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.canceled.connect(self._on_worker_canceled)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.progress.connect(self.progress_changed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.canceled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        self._thread.start()

    def cancel_analysis(self) -> None:
        self._restart_after_cleanup = False
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.cancel_analysis()
            self._thread.quit()
            self._thread.wait(2000)

    def _on_worker_finished(self, accumulator: BitActivityAccumulator) -> None:
        if self._scan_generation != self._generation:
            self._dirty = True
            self._restart_after_cleanup = self._active
            self.analysis_finished.emit()
            return
        self._accumulator = accumulator
        for chunk in self._pending_chunks:
            self._accumulator.ingest(chunk)
        self._pending_chunks.clear()
        self._results = {item.can_id: item for item in self._accumulator.snapshot()}
        self._ready = True
        self._dirty = False
        self.results_changed.emit(self.results, True)
        self.analysis_finished.emit()

    def _on_worker_canceled(self) -> None:
        self._dirty = True
        self._pending_chunks.clear()
        self.analysis_canceled.emit()
        self.analysis_finished.emit()

    def _on_worker_failed(self, message: str) -> None:
        self._dirty = True
        self._pending_chunks.clear()
        self.analysis_failed.emit(message)
        self.analysis_finished.emit()

    def _cleanup(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        restart = self._restart_after_cleanup and self._active
        self._restart_after_cleanup = False
        if restart:
            self._pending_chunks.clear()
            self.start_analysis()
        elif self._ready and self._pending_chunks:
            pending, self._pending_chunks = self._pending_chunks, []
            changed = []
            for chunk in pending:
                changed.extend(self._accumulator.ingest(chunk))
            for item in changed:
                self._results[item.can_id] = item
            if changed:
                self.results_changed.emit(tuple(changed), False)
