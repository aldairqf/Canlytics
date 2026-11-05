from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.reference_correlation import (
    CorrelationCanceled,
    ReferenceSource,
    TimedSeries,
    correlate_reference,
    resolve_reference_series,
)
import polars as pl


class _ReferenceCorrelationWorker(QObject):
    finished = QtSignal(object)
    failed = QtSignal(str)
    canceled = QtSignal()
    progress = QtSignal(int, int)

    def __init__(
        self,
        candidate: TimedSeries,
        reference: TimedSeries | ReferenceSource,
        options: dict[str, object],
        *,
        dataframe: pl.DataFrame,
        dbc_manager: object,
        candidates: tuple[object, ...],
        markers: tuple[dict, ...],
    ) -> None:
        super().__init__()
        self._candidate = candidate
        self._reference = reference
        self._options = dict(options)
        self._dataframe = dataframe
        self._dbc_manager = dbc_manager
        self._candidates = candidates
        self._markers = markers
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            reference = self._reference
            if isinstance(reference, ReferenceSource):
                reference = resolve_reference_series(
                    reference,
                    candidate_times=self._candidate.timestamps,
                    dataframe=self._dataframe,
                    dbc_manager=self._dbc_manager,
                    candidates=self._candidates,
                    markers=self._markers,
                )
            result = correlate_reference(
                self._candidate.timestamps,
                self._candidate.values,
                reference.timestamps,
                reference.values,
                should_cancel=lambda: self._cancel_requested,
                on_progress=lambda done, total: self.progress.emit(done, total),
                **self._options,
            )
        except CorrelationCanceled:
            self.canceled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit((result, reference))


class ReferenceCorrelationViewModel(QObject):
    analysis_started = QtSignal()
    analysis_progress = QtSignal(int, int)
    analysis_finished = QtSignal(object)
    analysis_failed = QtSignal(str)
    analysis_canceled = QtSignal()

    def __init__(self, dbc_manager: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._thread: QThread | None = None
        self._worker: _ReferenceCorrelationWorker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def analyze(
        self,
        candidate: TimedSeries,
        reference: TimedSeries | ReferenceSource,
        *,
        dataframe: pl.DataFrame,
        candidates: tuple[object, ...],
        markers: tuple[dict, ...],
        method: str,
        window_seconds: float,
        max_lag_seconds: float,
        lag_step_seconds: float,
        min_samples_per_window: int,
    ) -> None:
        if self.running:
            return
        self.analysis_started.emit()
        options: dict[str, object] = {
            "method": method,
            "window_seconds": window_seconds,
            "max_lag_seconds": max_lag_seconds,
            "lag_step_seconds": lag_step_seconds,
            "min_samples_per_window": min_samples_per_window,
        }
        self._thread = QThread(self)
        self._worker = _ReferenceCorrelationWorker(
            candidate,
            reference,
            options,
            dataframe=dataframe,
            dbc_manager=self._dbc_manager,
            candidates=candidates,
            markers=markers,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.analysis_progress)
        self._worker.finished.connect(self.analysis_finished)
        self._worker.failed.connect(self.analysis_failed)
        self._worker.canceled.connect(self.analysis_canceled)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.canceled.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        self._thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.cancel()
            self._thread.quit()
            self._thread.wait()

    def wait(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait()

    def _cleanup(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
