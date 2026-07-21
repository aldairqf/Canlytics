from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QObject, Signal as QtSignal

from services.candidate_interpretations import CandidateItem
from services.constraint_search import Constraint, ConstraintSearchCanceled, search_candidates


class ConstraintSearchWorker(QObject):
    finished = QtSignal(object, object)  # (list[SearchResult], SearchExclusions)
    canceled = QtSignal()
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(
        self, *, items: Sequence[CandidateItem], constraints: Sequence[Constraint],
        precision: float, tolerance: float,
    ):
        super().__init__()
        self._items = items
        self._constraints = constraints
        self._precision = precision
        self._tolerance = tolerance
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            results, exclusions = search_candidates(
                self._items, self._constraints,
                precision=self._precision, tolerance=self._tolerance,
                should_cancel=lambda: self._cancel_requested,
                on_progress=self.progress.emit,
            )
        except ConstraintSearchCanceled:
            self.canceled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        if self._cancel_requested:
            self.canceled.emit()
            return
        self.finished.emit(results, exclusions)
