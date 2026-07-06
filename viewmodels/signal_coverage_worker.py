from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from services.signal_coverage import (
    SignalCoverageCanceled,
    SignalCoverageItem,
    build_signal_coverage_report,
)


class _ProgressThrottle:
    """Only lets ~max_updates progress emissions through for the whole run,
    plus always the final one, regardless of how many signals are scanned."""

    def __init__(self, *, max_updates: int):
        self._max_updates = max(1, max_updates)
        self._step = 1
        self._last_emitted = 0

    def maybe_emit(self, done: int, total: int, signal: QtSignal) -> None:
        if self._step == 1 and total > self._max_updates:
            self._step = total // self._max_updates
        if done - self._last_emitted >= self._step or done == total:
            self._last_emitted = done
            signal.emit(done, total)


class SignalCoverageWorker(QObject):
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(self, *, df: pl.DataFrame, dbc_manager):
        super().__init__()
        self._df = df
        self._dbc_manager = dbc_manager
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        # A DBC can have thousands of signals -- emitting a cross-thread Qt
        # signal (and triggering a progress-bar repaint) for every single one
        # adds real overhead on top of the actual decode work. Cap emissions
        # to ~200 over the whole run regardless of signal count.
        throttle = _ProgressThrottle(max_updates=200)

        try:
            items: list[SignalCoverageItem] = build_signal_coverage_report(
                self._df,
                self._dbc_manager,
                should_cancel=lambda: self._cancel_requested,
                on_progress=lambda done, total: throttle.maybe_emit(done, total, self.progress),
            )
        except SignalCoverageCanceled:
            self.canceled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        if self._cancel_requested:
            self.canceled.emit()
            return
        self.finished.emit(items)
