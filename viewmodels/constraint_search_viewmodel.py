from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.candidate_interpretations import CandidateItem
from services.constraint_search import Constraint, SearchExclusions, SearchResult
from viewmodels.constraint_search_worker import ConstraintSearchWorker


class ConstraintSearchViewModel(QObject):
    search_started = QtSignal()
    search_finished = QtSignal()
    search_canceled = QtSignal()
    search_failed = QtSignal(str)
    progress_changed = QtSignal(int, int)
    results_changed = QtSignal(object, object)  # (list[SearchResult], SearchExclusions)

    def __init__(self, items: Sequence[CandidateItem], parent: QObject | None = None):
        super().__init__(parent)
        self._items = items
        self._thread: QThread | None = None
        self._worker: ConstraintSearchWorker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def run(self, constraints: Sequence[Constraint], *, precision: float, tolerance: float) -> None:
        if self.running:
            return
        self.search_started.emit()

        self._thread = QThread(self)
        self._worker = ConstraintSearchWorker(
            items=self._items, constraints=constraints, precision=precision, tolerance=tolerance,
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

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.cancel()
            self._thread.quit()
            self._thread.wait(2000)

    def _on_finished(self, results: list[SearchResult], exclusions: SearchExclusions) -> None:
        self.results_changed.emit(results, exclusions)
        self.search_finished.emit()

    def _on_canceled(self) -> None:
        self.search_canceled.emit()
        self.search_finished.emit()

    def _on_failed(self, message: str) -> None:
        self.search_failed.emit(message)
        self.search_finished.emit()

    def _cleanup(self) -> None:
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
