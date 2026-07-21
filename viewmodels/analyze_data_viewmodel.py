from __future__ import annotations

import logging
from collections import OrderedDict

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from models.mux_config import MuxConfigEntry
from services.analyze_data import (
    AnalyzeDataAccumulator,
    ByteSeries,
    MatrixEntry,
    build_accumulator,
    build_matrix_entries_for_id,
    detect_mux_cases,
    mux_bytes_for_can_id,
    mux_label_expr,
    sorted_can_ids,
)
from services.monotonic_changed_set import compute_changed_set_delta
from utils.can_id import can_id_sort_key
from viewmodels.analyze_data_matrix_worker import AnalyzeDataMatrixWorker
from viewmodels.analyze_data_precompute_worker import AnalyzeDataPrecomputeWorker

logger = logging.getLogger(__name__)

# Bound on the *lazy*, one-id-at-a-time cache so casually browsing many signals
# in a session can't grow memory unboundedly -- classic bounded-LRU eviction
# (same idea as browser tab discarding / an OS page cache), not a novel scheme.
# precompute_all() is a separate, explicit opt-in and deliberately bypasses this
# cap: the user asking to warm everything means they want everything resident.
_LAZY_CACHE_CAPACITY = 16


class AnalyzeDataViewModel(QObject):
    can_ids_changed = QtSignal(list)
    mux_cases_changed = QtSignal(list)
    summary_changed = QtSignal(dict)
    plot_changed = QtSignal(object)
    selected_id_changed = QtSignal(str)
    precompute_started = QtSignal()
    precompute_progress = QtSignal(int, int)
    precompute_finished = QtSignal()
    precompute_canceled = QtSignal()
    precompute_failed = QtSignal(str)
    matrix_started = QtSignal()
    matrix_progress = QtSignal(int, int)
    matrix_finished = QtSignal()
    matrix_canceled = QtSignal()
    matrix_failed = QtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._df = pl.DataFrame()
        self._selected_id: str | None = None
        self._selected_bytes: set[int] = set(range(8))
        self._mux_configs: list[MuxConfigEntry] = []
        self._selected_mux_case = "All"
        self._ts_min: float | None = None
        self._ts_max: float | None = None
        self._accumulator = AnalyzeDataAccumulator()
        self._watermark_height = 0
        self._seen_mux_labels: list[str] = []
        # Cache of already-visited CAN IDs (mux_case=="All" only -- set_selected_id
        # always resets to "All") so revisiting one this session is instant instead of
        # rebuilding via build_accumulator(). Keyed by can_id -> (accumulator,
        # mux_cases, seen_mux_labels). The entry for the *currently selected* id is
        # never stale: it's the same accumulator object still being fed live by
        # ingest_raw_chunk(), so caching it is just keeping a reference, not a copy.
        # OrderedDict so the lazy path can evict least-recently-used once over
        # _LAZY_CACHE_CAPACITY (see module docstring above).
        self._accumulator_cache: OrderedDict[str, tuple[AnalyzeDataAccumulator, list[str], list[str]]] = OrderedDict()
        self._precompute_thread: QThread | None = None
        self._precompute_worker: AnalyzeDataPrecomputeWorker | None = None
        # Matrix rollup: a small, independent summary (one decimated byte-series
        # per id) built via build_matrix_summary() -- never touches
        # _accumulator_cache, so opening the Matrix tab doesn't require (and isn't
        # bounded by) the full per-ID accumulator cache. See services/analyze_data.py.
        self._matrix_entries: list[MatrixEntry] = []
        self._matrix_built = False
        self._matrix_thread: QThread | None = None
        self._matrix_worker: AnalyzeDataMatrixWorker | None = None
        # AN3 Live mode: monotonic set of CAN IDs known to have movement in the
        # current Matrix. Grows via cheap per-touched-id checks in ingest_raw_chunk;
        # resynced to the authoritative full set (via compute_changed_set_delta)
        # whenever a batch build_matrix() completes -- see services/monotonic_changed_set.py.
        self._matrix_live = False
        self._matrix_live_ids: frozenset[str] = frozenset()

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @property
    def selected_bytes(self) -> set[int]:
        return set(self._selected_bytes)

    @property
    def mux_configs(self) -> list[MuxConfigEntry]:
        return list(self._mux_configs)

    def reset_dataframe(self, df: pl.DataFrame | None) -> None:
        """Wired to data_vm.dataframe_replaced -- drop incremental state on log reload."""
        self._df = df if df is not None else pl.DataFrame()
        self._accumulator = AnalyzeDataAccumulator()
        self._watermark_height = 0
        self._seen_mux_labels = []
        self._accumulator_cache = OrderedDict()
        self._matrix_entries = []
        self._matrix_built = False
        self._matrix_live_ids = frozenset()

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        self._df = df if df is not None else pl.DataFrame()
        ids = sorted_can_ids(self._df)
        self.can_ids_changed.emit(ids)
        id_changed = False
        if self._selected_id not in ids:
            self._selected_id = ids[0] if ids else None
            self.selected_id_changed.emit(self._selected_id or "")
            id_changed = True

        # Height mismatch = growth ingest_raw_chunk() didn't see (file append, etc).
        if id_changed or self._df.height != self._watermark_height:
            self._full_refresh()

    def set_selected_id(self, can_id: str | None) -> None:
        can_id = (can_id or "").strip().upper() or None
        if self._selected_id == can_id:
            return
        self._selected_id = can_id
        self.selected_id_changed.emit(self._selected_id or "")
        self._selected_mux_case = "All"

        cached = self._accumulator_cache.get(can_id) if can_id else None
        if cached is not None:
            self._accumulator_cache.move_to_end(can_id)  # LRU: mark most-recently-used
            self._accumulator, mux_cases, self._seen_mux_labels = cached
            self._watermark_height = self._df.height
            self.mux_cases_changed.emit(mux_cases)
            mux_bytes = self._mux_bytes_for_selected_id()
            self.summary_changed.emit(
                self._accumulator.snapshot(self._selected_id, mux_bytes, self._selected_mux_case)
            )
            self.plot_changed.emit(self._accumulator.plot_series(self._selected_bytes))
            return

        self._full_refresh()

    def set_selected_bytes(self, indexes: set[int]) -> None:
        self._selected_bytes = set(sorted(i for i in indexes if 0 <= i <= 7))
        # Only picks which already-accumulated series to plot -- no rescan needed.
        self.plot_changed.emit(self._accumulator.plot_series(self._selected_bytes))

    def emit_current_state(self) -> None:
        """Re-push summary + plot from the already-computed accumulator so a freshly
        reopened window syncs (BUGS.md B-26: the stats panel used to stay blank)."""
        mux_bytes = self._mux_bytes_for_selected_id()
        self.summary_changed.emit(
            self._accumulator.snapshot(self._selected_id, mux_bytes, self._selected_mux_case)
        )
        self.plot_changed.emit(self._accumulator.plot_series(self._selected_bytes))

    def set_mux_configuration(self, configs: list[MuxConfigEntry]) -> None:
        self._mux_configs = list(configs)
        self._selected_mux_case = "All"
        self._accumulator_cache = OrderedDict()  # mux geometry changed -- cached accumulators are stale
        self._full_refresh()

    def set_selected_mux_case(self, case_label: str) -> None:
        new_case = (case_label or "All").strip() or "All"
        if new_case == self._selected_mux_case:
            return
        self._selected_mux_case = new_case
        self._full_refresh()

    def set_time_range(self, ts_min: float | None, ts_max: float | None) -> None:
        self._ts_min = ts_min
        self._ts_max = ts_max
        self._accumulator_cache = OrderedDict()  # window changed -- cached accumulators are stale
        self._matrix_entries = []
        self._matrix_built = False  # matrix rollup was built over the old time window
        self._matrix_live_ids = frozenset()
        self._full_refresh()

    def ingest_raw_chunk(self, df_new: pl.DataFrame) -> None:
        """Fed by chunk_ready's raw pre-merge chunk -- merge_frames() can
        resort self._df, so a watermark against it would be unsafe."""
        if df_new is None or df_new.is_empty():
            return
        self._watermark_height += df_new.height
        self._invalidate_cache_touched_by(df_new)
        self._invalidate_matrix_touched_by(df_new)
        if not self._selected_id:
            return
        id_ts_filtered = self._filter_rows(df_new)
        if id_ts_filtered.is_empty():
            return
        mux_bytes = self._mux_bytes_for_selected_id()
        self._update_seen_mux_labels(id_ts_filtered, mux_bytes)
        case_filtered = self._apply_mux_case(id_ts_filtered, mux_bytes)
        if case_filtered.is_empty():
            return
        self._accumulator.feed(case_filtered)
        self.summary_changed.emit(
            self._accumulator.snapshot(self._selected_id, mux_bytes, self._selected_mux_case)
        )
        self.plot_changed.emit(self._accumulator.plot_series(self._selected_bytes))

    def _full_refresh(self) -> None:
        filtered = self._filter_rows(self._df)
        mux_bytes = self._mux_bytes_for_selected_id()
        mux_cases = ["All"] + detect_mux_cases(filtered, mux_bytes)
        self._seen_mux_labels = list(mux_cases[1:])
        if self._selected_mux_case not in mux_cases:
            self._selected_mux_case = "All"
        self.mux_cases_changed.emit(mux_cases)

        active = self._apply_mux_case(filtered, mux_bytes)
        self._accumulator = build_accumulator(active)
        self._watermark_height = self._df.height
        if self._selected_id and self._selected_mux_case == "All":
            self._remember_in_lazy_cache(self._selected_id, (self._accumulator, mux_cases, self._seen_mux_labels))
        self.summary_changed.emit(
            self._accumulator.snapshot(self._selected_id, mux_bytes, self._selected_mux_case)
        )
        self.plot_changed.emit(self._accumulator.plot_series(self._selected_bytes))

    def _remember_in_lazy_cache(self, can_id: str, entry: tuple) -> None:
        """Bounded-LRU insert for the organic browse-one-id-at-a-time path (see
        _LAZY_CACHE_CAPACITY). precompute_all()'s bulk fill bypasses this on
        purpose -- that path is the user's explicit "keep everything" opt-in."""
        self._accumulator_cache[can_id] = entry
        self._accumulator_cache.move_to_end(can_id)
        while len(self._accumulator_cache) > _LAZY_CACHE_CAPACITY:
            self._accumulator_cache.popitem(last=False)

    def free_memory(self) -> None:
        """Explicit "Free memory" action: drop every cached accumulator except the
        one currently on screen, releasing precompute_all()'s bulk cache (or an
        organically grown one) back down to just-in-time footprint."""
        keep = self._accumulator_cache.get(self._selected_id) if self._selected_id else None
        self._accumulator_cache = OrderedDict()
        if self._selected_id and keep is not None:
            self._accumulator_cache[self._selected_id] = keep

    def _invalidate_cache_touched_by(self, df_new: pl.DataFrame) -> None:
        # The currently selected id's cache entry is the same accumulator object
        # still being fed live below -- only ids sitting idle in cache go stale.
        if "ID" not in df_new.columns or not self._accumulator_cache:
            return
        touched_ids = set(df_new["ID"].unique().to_list())
        touched_ids.discard(self._selected_id)
        for can_id in touched_ids:
            self._accumulator_cache.pop(can_id, None)

    def _invalidate_matrix_touched_by(self, df_new: pl.DataFrame) -> None:
        if not self._matrix_built or "ID" not in df_new.columns:
            return
        touched_ids = set(df_new["ID"].unique().to_list())
        if self._matrix_live:
            self._live_update_matrix(touched_ids)
            return
        if any(e.can_id in touched_ids for e in self._matrix_entries):
            self._matrix_built = False

    def set_matrix_live(self, enabled: bool) -> None:
        """AN3: while enabled, a CAN ID that starts moving is spliced into the
        already-built Matrix reactively instead of requiring a manual refresh."""
        self._matrix_live = bool(enabled)
        if self._matrix_live and self._matrix_built:
            self._matrix_live_ids = frozenset(e.can_id for e in self._matrix_entries if e.has_movement)

    def _live_update_matrix(self, touched_ids: set[str]) -> None:
        # Ids already known to have movement don't need re-checking -- only ids
        # never-seen or previously flat could newly qualify for the "grew" case.
        candidates = touched_ids - self._matrix_live_ids
        if not candidates:
            return
        ts_filtered = self._filter_ts_range(self._df)
        spliced = False
        for can_id in candidates:
            entries = build_matrix_entries_for_id(ts_filtered, can_id)
            if not entries:
                continue
            self._splice_matrix_entries(can_id, entries)
            spliced = True
        if not spliced:
            return
        snapshot = frozenset(e.can_id for e in self._matrix_entries if e.has_movement)
        delta = compute_changed_set_delta(self._matrix_live_ids, snapshot)
        if delta.reset:
            logger.debug(
                "Matrix Live tracking resynced during incremental update: %d -> %d moving id(s)",
                len(self._matrix_live_ids), len(snapshot),
            )
        self._matrix_live_ids = snapshot
        self.matrix_finished.emit()

    def _splice_matrix_entries(self, can_id: str, entries: list[MatrixEntry]) -> None:
        self._matrix_entries = [e for e in self._matrix_entries if e.can_id != can_id] + entries

    def _filter_rows(self, df: pl.DataFrame) -> pl.DataFrame:
        if df is None or df.is_empty() or not self._selected_id or "ID" not in df.columns:
            return pl.DataFrame()
        predicate = pl.col("ID") == self._selected_id
        if "TS" in df.columns:
            if self._ts_min is not None:
                predicate = predicate & (pl.col("TS") >= float(self._ts_min))
            if self._ts_max is not None:
                predicate = predicate & (pl.col("TS") <= float(self._ts_max))
        return df.filter(predicate)

    def _apply_mux_case(self, df: pl.DataFrame, mux_bytes: tuple[int, ...]) -> pl.DataFrame:
        if df.is_empty() or not mux_bytes or self._selected_mux_case == "All":
            return df
        return df.filter(mux_label_expr(mux_bytes) == self._selected_mux_case)

    def _mux_bytes_for_selected_id(self) -> tuple[int, ...]:
        return mux_bytes_for_can_id(self._mux_configs, self._selected_id or "")

    def _filter_ts_range(self, df: pl.DataFrame) -> pl.DataFrame:
        if df is None or df.is_empty() or "TS" not in df.columns:
            return df
        predicate = None
        if self._ts_min is not None:
            predicate = pl.col("TS") >= float(self._ts_min)
        if self._ts_max is not None:
            max_pred = pl.col("TS") <= float(self._ts_max)
            predicate = max_pred if predicate is None else predicate & max_pred
        return df.filter(predicate) if predicate is not None else df

    @property
    def precompute_running(self) -> bool:
        return self._precompute_thread is not None and self._precompute_thread.isRunning()

    @property
    def matrix_built(self) -> bool:
        return self._matrix_built

    @property
    def matrix_running(self) -> bool:
        return self._matrix_thread is not None and self._matrix_thread.isRunning()

    def get_matrix_entries(self, *, hide_flat: bool = False) -> list[MatrixEntry]:
        """AN1: reads the independent matrix rollup built by build_matrix() --
        does NOT depend on _accumulator_cache (see build_matrix_summary)."""
        entries = list(self._matrix_entries)
        if hide_flat:
            entries = [e for e in entries if e.has_movement]
        entries.sort(key=lambda e: can_id_sort_key(e.can_id))
        return entries

    def build_matrix(self, *, force: bool = False) -> None:
        """Build (or reuse, if already built and not stale) the Matrix rollup.
        Independent of precompute_all() -- opening the Matrix tab never requires
        warming the full per-ID accumulator cache."""
        if self.matrix_running:
            return
        if force:
            self._matrix_built = False
        if self._matrix_built:
            self.matrix_finished.emit()
            return
        if self._df.is_empty():
            self._matrix_entries = []
            self._matrix_built = True
            self.matrix_finished.emit()
            return
        ts_filtered = self._filter_ts_range(self._df)
        ids = sorted_can_ids(ts_filtered)
        if not ids:
            self._matrix_entries = []
            self._matrix_built = True
            self.matrix_finished.emit()
            return

        self.matrix_started.emit()
        self._matrix_thread = QThread(self)
        self._matrix_worker = AnalyzeDataMatrixWorker(df=ts_filtered, can_ids=ids)
        self._matrix_worker.moveToThread(self._matrix_thread)
        self._matrix_thread.started.connect(self._matrix_worker.run)
        self._matrix_worker.finished.connect(self._on_matrix_finished)
        self._matrix_worker.canceled.connect(self._on_matrix_canceled)
        self._matrix_worker.failed.connect(self._on_matrix_failed)
        self._matrix_worker.progress.connect(self.matrix_progress)
        self._matrix_worker.finished.connect(self._matrix_thread.quit)
        self._matrix_worker.canceled.connect(self._matrix_thread.quit)
        self._matrix_worker.failed.connect(self._matrix_thread.quit)
        self._matrix_thread.finished.connect(self._cleanup_matrix)
        self._matrix_thread.start()

    def cancel_matrix(self) -> None:
        if self._matrix_worker is not None:
            self._matrix_worker.cancel()

    def _on_matrix_finished(self, result: list) -> None:
        self._matrix_entries = result
        self._matrix_built = True
        snapshot = frozenset(e.can_id for e in result if e.has_movement)
        delta = compute_changed_set_delta(self._matrix_live_ids, snapshot)
        if delta.reset:
            logger.debug(
                "Matrix Live tracking resynced by a full rebuild: %d -> %d moving id(s)",
                len(self._matrix_live_ids), len(snapshot),
            )
        self._matrix_live_ids = snapshot
        self.matrix_finished.emit()

    def _on_matrix_canceled(self) -> None:
        self.matrix_canceled.emit()

    def _on_matrix_failed(self, message: str) -> None:
        self.matrix_failed.emit(message)

    def _cleanup_matrix(self) -> None:
        if self._matrix_worker:
            self._matrix_worker.deleteLater()
            self._matrix_worker = None
        if self._matrix_thread:
            self._matrix_thread.deleteLater()
            self._matrix_thread = None

    def precompute_all(self) -> None:
        """Eagerly warm the accumulator cache for every not-yet-cached CAN ID, so
        switching between them afterward is instant instead of paying the first-visit
        cost per id -- the modal progress dialog is the tradeoff the user chose."""
        if self.precompute_running or self._df.is_empty():
            return
        ts_filtered = self._filter_ts_range(self._df)
        ids = [
            can_id for can_id in sorted_can_ids(ts_filtered)
            if can_id != self._selected_id and can_id not in self._accumulator_cache
        ]
        if not ids:
            self.precompute_finished.emit()
            return

        mux_configs_snapshot = list(self._mux_configs)

        def mux_bytes_for_id(can_id: str) -> tuple[int, ...]:
            return mux_bytes_for_can_id(mux_configs_snapshot, can_id)

        self.precompute_started.emit()
        self._precompute_thread = QThread(self)
        self._precompute_worker = AnalyzeDataPrecomputeWorker(
            df=ts_filtered, can_ids=ids, mux_bytes_for_id=mux_bytes_for_id,
        )
        self._precompute_worker.moveToThread(self._precompute_thread)
        self._precompute_thread.started.connect(self._precompute_worker.run)
        self._precompute_worker.finished.connect(self._on_precompute_finished)
        self._precompute_worker.canceled.connect(self._on_precompute_canceled)
        self._precompute_worker.failed.connect(self._on_precompute_failed)
        self._precompute_worker.progress.connect(self.precompute_progress)
        self._precompute_worker.finished.connect(self._precompute_thread.quit)
        self._precompute_worker.canceled.connect(self._precompute_thread.quit)
        self._precompute_worker.failed.connect(self._precompute_thread.quit)
        self._precompute_thread.finished.connect(self._cleanup_precompute)
        self._precompute_thread.start()

    def cancel_precompute(self) -> None:
        if self._precompute_worker is not None:
            self._precompute_worker.cancel()

    def shutdown(self) -> None:
        if self._precompute_thread is not None and self._precompute_thread.isRunning():
            self.cancel_precompute()
            self._precompute_thread.quit()
            self._precompute_thread.wait(2000)
        if self._matrix_thread is not None and self._matrix_thread.isRunning():
            self.cancel_matrix()
            self._matrix_thread.quit()
            self._matrix_thread.wait(2000)

    def _on_precompute_finished(self, result: dict) -> None:
        for can_id, (accumulator, mux_cases) in result.items():
            if can_id == self._selected_id or can_id in self._accumulator_cache:
                continue
            self._accumulator_cache[can_id] = (accumulator, mux_cases, list(mux_cases[1:]))
        self.precompute_finished.emit()

    def _on_precompute_canceled(self) -> None:
        self.precompute_canceled.emit()

    def _on_precompute_failed(self, message: str) -> None:
        self.precompute_failed.emit(message)

    def _cleanup_precompute(self) -> None:
        if self._precompute_worker:
            self._precompute_worker.deleteLater()
            self._precompute_worker = None
        if self._precompute_thread:
            self._precompute_thread.deleteLater()
            self._precompute_thread = None

    def _update_seen_mux_labels(self, id_ts_filtered_new_rows: pl.DataFrame, mux_bytes: tuple[int, ...]) -> None:
        if not mux_bytes:
            return
        new_labels = detect_mux_cases(id_ts_filtered_new_rows, mux_bytes)
        added = [label for label in new_labels if label not in self._seen_mux_labels]
        if added:
            self._seen_mux_labels.extend(added)
            self.mux_cases_changed.emit(["All"] + self._seen_mux_labels)
