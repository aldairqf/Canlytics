from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, QThread, QTimer, Signal as QtSignal

from services.range_diff import (
    ByteObservation,
    DiffOptions,
    LiveByteAccumulator,
    RangeDiffReport,
    TimeRange,
    build_live_diff_report,
    dbc_hint_for_byte,
    extract_byte_series,
    feed_live_accumulators,
    frame_density,
    observe_dataframe_bytes,
)
from viewmodels.range_diff_worker import RangeDiffWorker

_DENSITY_BUCKETS = 200  # timeline histogram resolution
_INITIAL_BAND_FRACTION = 0.1  # initial A/B band width, as a fraction of the log span
_LIVE_TICK_MS = 1000  # how often the live report is reclassified


class RangeDiffViewModel(QObject):
    analysis_started = QtSignal()
    analysis_finished = QtSignal()
    analysis_failed = QtSignal(str)
    analysis_canceled = QtSignal()
    progress_changed = QtSignal(int, int)
    report_changed = QtSignal(object)
    visible_changed = QtSignal(list)
    density_changed = QtSignal(object)
    ranges_changed = QtSignal(object)
    live_active_changed = QtSignal(bool)

    def __init__(self, dbc_manager, parent: QObject | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._df = pl.DataFrame()
        self._range_a = TimeRange(start=0.0, end=0.0)
        self._range_b = TimeRange(start=0.0, end=0.0)
        self._options = DiffOptions()
        self._report: RangeDiffReport | None = None
        self._thread: QThread | None = None
        self._worker: RangeDiffWorker | None = None

        self._live_active = False
        self._live_baseline: dict[str, list[ByteObservation | None]] = {}
        self._live_acc: dict[str, list[LiveByteAccumulator]] = {}
        self._live_watermark = 0
        self._live_range_a = TimeRange(start=0.0, end=0.0)
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._live_tick)

    @property
    def report(self) -> RangeDiffReport | None:
        return self._report

    @property
    def range_a(self) -> TimeRange:
        return self._range_a

    @property
    def range_b(self) -> TimeRange:
        return self._range_b

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @property
    def options(self) -> DiffOptions:
        return self._options

    @property
    def is_live(self) -> bool:
        return self._live_active

    @property
    def live_range_a(self) -> TimeRange:
        return self._live_range_a

    def get_byte_series(self, can_id: str, byte_index: int) -> tuple[list[float], list[int]]:
        return extract_byte_series(self._df, can_id, byte_index)

    def get_byte_dbc_hint(self, can_id: str, byte_index: int) -> str | None:
        return dbc_hint_for_byte(self._dbc_manager, can_id, byte_index)

    def reset_dataframe(self, df: pl.DataFrame | None) -> None:
        """Full reload: recompute density, reset the A/B bands, and drop any live session
        -- the baseline/watermark it holds refer to a dataframe that no longer exists."""
        self.stop_live()
        self._df = df if df is not None else pl.DataFrame()
        edges, counts = frame_density(self._df, buckets=_DENSITY_BUCKETS)
        self.density_changed.emit((edges, counts))
        self._reset_ranges_to_log_extremes()

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        """Cheap per-chunk update -- leaves density/bands untouched."""
        self._df = df if df is not None else pl.DataFrame()
        if self._live_active:
            self._feed_live_from_watermark()

    def emit_current_state(self) -> None:
        """Re-push density, ranges, live state and any report so a freshly-opened window syncs."""
        edges, counts = frame_density(self._df, buckets=_DENSITY_BUCKETS)
        self.density_changed.emit((edges, counts))
        self.ranges_changed.emit((self._range_a, self._range_b))
        self.live_active_changed.emit(self._live_active)
        if self._report is not None:
            # report_changed first: the view rebuilds its full (unfiltered) tree from
            # it, then visible_changed drives which rows are actually shown (B-15).
            self.report_changed.emit(self._report)
            self.visible_changed.emit(self._report.visible(self._options))

    def _reset_ranges_to_log_extremes(self) -> None:
        if self._df.is_empty():
            self._range_a = TimeRange(start=0.0, end=0.0)
            self._range_b = TimeRange(start=0.0, end=0.0)
        else:
            tmin = float(self._df.get_column("TS").min())
            tmax = float(self._df.get_column("TS").max())
            span = tmax - tmin
            width = span * _INITIAL_BAND_FRACTION if span > 0 else 0.0
            self._range_a = TimeRange(start=tmin, end=tmin + width)
            self._range_b = TimeRange(start=tmax - width, end=tmax)
        self.ranges_changed.emit((self._range_a, self._range_b))

    def set_range_a(self, start: float, end: float) -> None:
        self._range_a = TimeRange(start=start, end=end)
        self.ranges_changed.emit((self._range_a, self._range_b))

    def set_range_b(self, start: float, end: float) -> None:
        self._range_b = TimeRange(start=start, end=end)
        self.ranges_changed.emit((self._range_a, self._range_b))

    def set_options(self, opts: DiffOptions) -> None:
        self._options = opts
        if self._report is not None:
            self.visible_changed.emit(self._report.visible(self._options))

    def capture_live_baseline(self) -> None:
        """Freeze A = everything accumulated so far; B grows from this instant forward."""
        if self._df.is_empty() or self.running:
            return
        self.stop_live()
        self._live_baseline = observe_dataframe_bytes(self._df)
        self._live_acc = {}
        self._live_watermark = self._df.height
        tmin = float(self._df.get_column("TS").min())
        tmax = float(self._df.get_column("TS").max())
        self._live_range_a = TimeRange(start=tmin, end=tmax)
        self._live_active = True
        self.live_active_changed.emit(True)
        self._live_timer.start(_LIVE_TICK_MS)
        self._live_tick()

    def stop_live(self) -> None:
        if not self._live_active:
            return
        self._live_active = False
        self._live_timer.stop()
        self.live_active_changed.emit(False)

    def _feed_live_from_watermark(self) -> None:
        if self._df.height <= self._live_watermark:
            return
        new_slice = self._df.slice(self._live_watermark, self._df.height - self._live_watermark)
        self._live_watermark = self._df.height
        feed_live_accumulators(self._live_acc, new_slice)

    def _live_tick(self) -> None:
        if not self._live_active:
            return
        now = float(self._df.get_column("TS").max()) if not self._df.is_empty() else self._live_range_a.end
        report = build_live_diff_report(
            self._live_baseline, self._live_acc,
            range_a=self._live_range_a, now=now, dbc_manager=self._dbc_manager,
        )
        self._report = report
        self.report_changed.emit(report)
        self.visible_changed.emit(report.visible(self._options))

    def run(self) -> None:
        if self.running or self._df.is_empty():
            return

        self.stop_live()
        self.analysis_started.emit()

        self._thread = QThread(self)
        self._worker = RangeDiffWorker(
            df=self._df,
            range_a=self._range_a,
            range_b=self._range_b,
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

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def cancel_and_wait_batch(self) -> None:
        """B-19: window close should wait for an in-flight batch compare to actually
        stop -- unlike shutdown(), this never touches an active Live session, which
        must survive the window closing (the vm outlives it)."""
        if self._thread is not None and self._thread.isRunning():
            self.cancel()
            self._thread.quit()
            self._thread.wait(2000)

    def shutdown(self) -> None:
        self.stop_live()
        if self._thread is not None and self._thread.isRunning():
            self.cancel()
            self._thread.quit()
            self._thread.wait(2000)

    def _on_finished(self, report: RangeDiffReport) -> None:
        self._report = report
        self.report_changed.emit(report)
        self.visible_changed.emit(report.visible(self._options))
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
