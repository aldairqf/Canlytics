from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal, QTimer

from services.can_data_parser import FORMAT_KVASER_MEMORATOR, empty_frame, inspect_log_metadata
from services.can_log import CANLog
from services.log_data import is_append_in_order, merge_frames

# Only rechunk every Nth flush -- see merge_frames()'s rechunk param.
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
    rows_appended = QtSignal(object, object)
    can_ids_changed = QtSignal(list)
    unsaved_capture_changed = QtSignal(bool)

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
        self._all_ids: set[str] = set()
        self._sorted_ids: tuple[str, ...] = ()
        self._flush_count = 0
        self._has_unsaved_capture = False
        self._unsaved_capture_frame_count = 0
        self._data_revision = 0
        self._source_paths: set[str] = set()

    @property
    def has_unsaved_capture(self) -> bool:
        return self._has_unsaved_capture

    @property
    def unsaved_capture_frame_count(self) -> int:
        return self._unsaved_capture_frame_count

    def mark_capture_saved(self, *, expected_revision: int | None = None) -> bool:
        if expected_revision is not None and expected_revision != self._data_revision:
            return False
        self._unsaved_capture_frame_count = 0
        self._set_unsaved_capture(False)
        return True

    @property
    def data_revision(self) -> int:
        return self._data_revision

    @property
    def source_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._source_paths))

    def _set_unsaved_capture(self, value: bool) -> None:
        if value == self._has_unsaved_capture:
            return
        self._has_unsaved_capture = value
        if not value:
            self._unsaved_capture_frame_count = 0
        self.unsaved_capture_changed.emit(value)

    @property
    def df(self) -> pl.DataFrame | None:
        return self._df_all

    @property
    def normalize(self) -> bool:
        return self._normalize

    @property
    def has_reloadable_log(self) -> bool:
        return self._log is not None

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
        new_log = CANLog(path)
        dataframe = new_log.load(self._normalize)
        self._log = new_log
        self._df_all = dataframe
        self._source_paths = {str(new_log.path.resolve())}
        self._data_revision += 1
        self._set_unsaved_capture(False)
        self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        self._replace_ids(self._df_all)

    def append_log(self, path: str):
        new_log = CANLog(path)
        df_new = new_log.load(normalize_time=False)

        if df_new.is_empty():
            return
        self._source_paths.add(str(new_log.path.resolve()))

        if self._df_all is None or self._df_all.is_empty():
            self._log = new_log

        base = self._df_all
        append_in_order = is_append_in_order(base, df_new, normalize=self._normalize)
        new_ids = self._remember_ids(df_new)
        delta = self._normalize_delta(base, df_new) if append_in_order else None
        self._df_all = merge_frames(base, df_new, normalize=self._normalize)
        self._data_revision += 1

        if append_in_order:
            self.rows_appended.emit(delta, new_ids)
        else:
            self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        if new_ids:
            self.can_ids_changed.emit(list(self._sorted_ids))

    def set_normalize(self, value: bool):
        self._normalize = value
        if not self._log:
            return

        self._pending_chunks.clear()
        self._pending_timer.stop()
        self._df_all = self._log.load(self._normalize)
        self._data_revision += 1
        self._set_unsaved_capture(False)
        self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        self._replace_ids(self._df_all)

    def replace_log(self, path: str, df: pl.DataFrame, *, source_tz_offset_minutes: int | None = None):
        new_log = CANLog(path, source_tz_offset_minutes=source_tz_offset_minutes)
        self._pending_chunks.clear()
        self._pending_timer.stop()
        self._log = new_log
        self._df_all = df
        self._source_paths = {str(new_log.path.resolve())}
        self._data_revision += 1
        self._set_unsaved_capture(False)
        self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        self._replace_ids(self._df_all)

    def append_df(self, df_new: pl.DataFrame, *, unsaved: bool = True):
        if df_new.is_empty():
            return
        self._data_revision += 1
        if unsaved:
            self._unsaved_capture_frame_count += df_new.height
            self._set_unsaved_capture(True)
        self._pending_chunks.append(df_new)
        if not self._pending_timer.isActive():
            self._pending_timer.start()

    def clear(self):
        self._set_unsaved_capture(False)
        self._pending_chunks.clear()
        self._pending_timer.stop()
        self._flush_count = 0
        self._log = None
        self._source_paths.clear()
        self._data_revision += 1
        self._df_all = empty_frame()
        self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        self._replace_ids(self._df_all)

    @staticmethod
    def _ids_in(dataframe: pl.DataFrame | None) -> set[str]:
        if dataframe is None or dataframe.is_empty() or "ID" not in dataframe.columns:
            return set()
        return {str(can_id) for can_id in dataframe["ID"].unique().to_list() if can_id is not None}

    def _remember_ids(self, incoming: pl.DataFrame) -> tuple[str, ...]:
        new_ids = tuple(sorted(self._ids_in(incoming) - self._all_ids))
        if new_ids:
            self._all_ids.update(new_ids)
            self._sorted_ids = tuple(sorted(self._all_ids))
        return new_ids

    def _replace_ids(self, dataframe: pl.DataFrame | None) -> None:
        previous_ids = self._sorted_ids
        self._all_ids = self._ids_in(dataframe)
        self._sorted_ids = tuple(sorted(self._all_ids))
        if self._sorted_ids != previous_ids:
            self.can_ids_changed.emit(list(self._sorted_ids))

    def _normalize_delta(
        self,
        base: pl.DataFrame | None,
        incoming: pl.DataFrame,
    ) -> pl.DataFrame:
        if not self._normalize or base is None or base.is_empty():
            return incoming
        base_start_ts = float(base[0, "TS"])
        return incoming.with_columns((pl.col("TS") - base_start_ts).round(6).alias("TS"))

    def flush_pending(self) -> None:
        self._pending_timer.stop()
        self._flush_pending()

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
        base = self._df_all
        append_in_order = is_append_in_order(base, merged_incoming, normalize=self._normalize)
        new_ids = self._remember_ids(merged_incoming)
        delta = self._normalize_delta(base, merged_incoming) if append_in_order else None
        self._df_all = merge_frames(
            base,
            merged_incoming,
            normalize=self._normalize,
            rechunk=do_rechunk,
        )

        if append_in_order:
            self.rows_appended.emit(delta, new_ids)
        else:
            self.dataframe_replaced.emit(self._df_all)
        self.dataframe_changed.emit(self._df_all)
        if new_ids:
            self.can_ids_changed.emit(list(self._sorted_ids))
