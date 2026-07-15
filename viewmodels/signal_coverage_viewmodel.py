from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from services.signal_coverage import SignalCoverageItem, build_can_id_index, refresh_last_values
from viewmodels.signal_coverage_worker import SignalCoverageWorker


class SignalCoverageViewModel(QObject):
    analysis_started = QtSignal()
    analysis_finished = QtSignal()
    analysis_failed = QtSignal(str)
    analysis_canceled = QtSignal()
    results_changed = QtSignal(object)
    progress_changed = QtSignal(int, int)
    # Emits only the items whose last_value moved, so the window can patch
    # those table cells instead of rebuilding the whole table on every
    # incoming chunk while streaming.
    last_values_changed = QtSignal(object)

    def __init__(self, dbc_manager, parent: QObject | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._df = pl.DataFrame()
        self._thread: QThread | None = None
        self._worker: SignalCoverageWorker | None = None
        self._results: list[SignalCoverageItem] = []
        # can_id -> indexes into _results; rebuilt in _on_finished() whenever
        # _results changes, so ingest_df() never has to scan every result.
        self._can_id_index: dict[int, list[int]] = {}
        # True strictly between start_analysis() and the worker's
        # finished/canceled/failed callback -- deliberately not derived from
        # QThread.isRunning(), which can still read True for a moment after the
        # worker's own "finished" callback already ran (quit() was only just
        # requested), which would let ingest_df() buffer a chunk that then sits
        # unapplied until some future scan.
        self._scanning = False
        # Chunks that arrived via ingest_df() while a scan was in flight --
        # replayed once that scan's results land (see _on_finished). A scan's
        # SignalCoverageWorker snapshots self._df once at start_analysis(); any
        # chunk_ready frames that arrive after that snapshot were never seen by
        # the scan and must be applied to its results afterwards.
        self._pending_during_scan: list[pl.DataFrame] = []

    @property
    def results(self) -> list[SignalCoverageItem]:
        return list(self._results)

    def reset_dataframe(self, df: pl.DataFrame | None) -> None:
        """The dataframe was swapped wholesale (new/reloaded log), not appended
        to -- any chunks buffered for the previous (now irrelevant) dataset
        must not be replayed against it. The stale results themselves are left
        as-is, same as every other stat column: they only refresh on the next
        "Analyze"."""
        self._df = df if df is not None else pl.DataFrame()
        self._pending_during_scan.clear()

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        """Keeps the accumulated-log snapshot used by start_analysis() current.
        Live last_value updates do NOT derive from this -- see ingest_df()."""
        self._df = df if df is not None else pl.DataFrame()

    def ingest_df(self, df_new: pl.DataFrame) -> None:
        """Refresh last_value from a freshly-arrived RAW chunk (pre-merge),
        fed by ConnectionStreamViewModel.chunk_ready -- the same source
        RealTimeAnalysisViewModel.ingest_df() uses. This is the actual
        incremental unit; it is deliberately NOT derived by diffing the
        accumulated dataframe (set_dataframe()'s self._df), because
        merge_frames() (services/log_data.py) re-sorts that WHOLE dataframe by
        TS whenever a chunk arrives slightly out of order (routine with live
        streaming/multi-bus jitter) -- any row-count or timestamp watermark
        against it can end up permanently skipping whatever got sorted to a
        position at or before the watermark, even though it's genuinely new.
        Reading the untouched, pre-merge chunk directly sidesteps that
        entirely.
        """
        if df_new is None or df_new.is_empty():
            return
        if self._scanning:
            self._pending_during_scan.append(df_new)
            return
        self._apply_chunk(df_new)

    def _apply_chunk(self, df_new: pl.DataFrame) -> None:
        if not self._results:
            return
        updated = refresh_last_values(self._results, df_new, self._can_id_index)
        changed = [item for old, item in zip(self._results, updated) if item is not old]
        self._results = updated
        if changed:
            self.last_values_changed.emit(changed)

    def start_analysis(self) -> None:
        if self.running:
            return

        self.analysis_started.emit()
        self._scanning = True
        self._pending_during_scan.clear()

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
        self._can_id_index = build_can_id_index(items)
        self._end_scan()
        self.results_changed.emit(self._results)
        self.analysis_finished.emit()

    def _on_canceled(self) -> None:
        # The scan produced no new results -- self._results is still whatever
        # was displayed before start_analysis(); chunks that arrived during the
        # canceled attempt still belong against that (still-current) list.
        self._end_scan()
        self.analysis_canceled.emit()
        self.analysis_finished.emit()

    def _on_failed(self, message: str) -> None:
        self._end_scan()
        self.analysis_failed.emit(message)
        self.analysis_finished.emit()

    def _end_scan(self) -> None:
        self._scanning = False
        pending, self._pending_during_scan = self._pending_during_scan, []
        for chunk in pending:
            self._apply_chunk(chunk)

    def _cleanup(self) -> None:
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
