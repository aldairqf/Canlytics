from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal, QTimer

from config.defaults import DEFAULT_COLUMNS
from services.can_data_parser import FORMAT_KVASER_MEMORATOR, inspect_log_metadata
from services.can_log import CANLog
from services.log_data import merge_frames

# merge_frames(rechunk=True) is an O(total rows) copy -- fine for a one-shot
# append, but paying it on every ~100ms streaming flush (_flush_pending)
# degrades a long live session. Skip it on most flushes and only pay the
# cost periodically, bounding how fragmented the accumulated dataframe gets.
_RECHUNK_EVERY_N_FLUSHES = 20


class LogDataViewModel(QObject):
    dataframe_changed = QtSignal(object)
    # Emitted (before dataframe_changed) only when the dataframe is swapped
    # wholesale rather than appended to -- consumers that keep an incremental
    # "new rows since last time" watermark (e.g. SignalCoverageViewModel) need
    # this to tell "a different/reloaded log" apart from "more frames arrived",
    # which a plain row-count comparison can't do (a reloaded log can easily be
    # the same size or larger).
    dataframe_replaced = QtSignal(object)
    can_ids_changed = QtSignal(list)

    def __init__(self):
        super().__init__()
        self._log: CANLog | None = None
        self._df_all = None
        self._normalize = False
        self._pending_chunks: list[pl.DataFrame] = []
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.setInterval(100)
        self._pending_timer.timeout.connect(self._flush_pending)
        self._last_ids: tuple[str, ...] = ()
        self._flush_count = 0

    @property
    def df(self) -> pl.DataFrame | None:
        return self._df_all

    @property
    def normalize(self) -> bool:
        return self._normalize

    def kvaser_timestamp_prompt_text(self, path: str) -> str | None:
        """Return the log's recorded creation timestamp text if *path* is a
        Kvaser Memorator log that has one, else None (no timezone prompt
        needed)."""
        metadata = inspect_log_metadata(path)
        if metadata.format != FORMAT_KVASER_MEMORATOR or not metadata.created_at_text:
            return None
        return metadata.created_at_text

    def load_log(self, path: str):
        self._pending_chunks.clear()
        self._pending_timer.stop()
        self._log = CANLog(path)
        self._df_all = self._log.load(self._normalize)
        self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def append_log(self, path: str):
        new_log = CANLog(path)
        df_new = new_log.load(normalize_time=False)

        if df_new.is_empty():
            return

        if self._df_all is None or self._df_all.is_empty():
            self._log = new_log

        self._df_all = merge_frames(
            self._df_all,
            df_new,
            normalize=self._normalize,
        )

        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def set_normalize(self, value: bool):
        self._normalize = value
        if not self._log:
            return

        self._pending_chunks.clear()
        self._pending_timer.stop()
        self._df_all = self._log.load(self._normalize)
        self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def replace_log(self, path: str, df: pl.DataFrame, *, source_tz_offset_minutes: int | None = None):
        self._pending_chunks.clear()
        self._pending_timer.stop()
        self._log = CANLog(path, source_tz_offset_minutes=source_tz_offset_minutes)
        self._df_all = df
        self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def append_df(self, df_new: pl.DataFrame):
        if df_new.is_empty():
            return
        self._pending_chunks.append(df_new)
        if not self._pending_timer.isActive():
            self._pending_timer.start()

    def clear(self):
        self._pending_chunks.clear()
        self._pending_timer.stop()
        self._flush_count = 0
        self._log = None
        self._df_all = pl.DataFrame({c: [] for c in DEFAULT_COLUMNS})
        self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()

    def _emit_ids(self):
        if self._df_all is None or "ID" not in self._df_all.columns:
            if self._last_ids:
                self._last_ids = ()
                self.can_ids_changed.emit([])
            return

        ids = tuple(sorted(self._df_all["ID"].unique().to_list()))
        if ids == self._last_ids:
            return
        self._last_ids = ids
        self.can_ids_changed.emit(list(ids))

    def _flush_pending(self):
        if not self._pending_chunks:
            return
        if len(self._pending_chunks) == 1:
            merged_incoming = self._pending_chunks[0]
        else:
            merged_incoming = pl.concat(self._pending_chunks, how="vertical", rechunk=True)
        self._pending_chunks.clear()

        self._flush_count += 1
        do_rechunk = self._flush_count % _RECHUNK_EVERY_N_FLUSHES == 0
        self._df_all = merge_frames(
            self._df_all,
            merged_incoming,
            normalize=self._normalize,
            rechunk=do_rechunk,
        )

        self.dataframe_changed.emit(self._df_all)
        self._emit_ids()
