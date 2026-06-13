from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from models.mux_config import MuxConfigEntry
from services.candidate_interpretations import (
    CandidateInterpretationsCanceled,
    CandidateItem,
    CandidateSeries,
    _build_candidate_items,
    _format_number,
)
from utils.can_id import can_id_sort_key


class _CandidateInterpretationsWorker(QObject):
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)

    def __init__(
        self,
        *,
        df: pl.DataFrame,
        checked_ids: set[str],
        mux_configs: list[MuxConfigEntry],
        min_length: int,
        max_length: int,
        granularity: int,
        endianness: str,
        value_type: str,
        sensitivity: int,
    ):
        super().__init__()
        self._df = df
        self._checked_ids = set(checked_ids)
        self._mux_configs = list(mux_configs)
        self._min_length = min_length
        self._max_length = max_length
        self._granularity = granularity
        self._endianness = endianness
        self._value_type = value_type
        self._sensitivity = sensitivity
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def run(self) -> None:
        try:
            items = _build_candidate_items(
                self._df,
                checked_ids=self._checked_ids,
                mux_configs=self._mux_configs,
                min_length=self._min_length,
                max_length=self._max_length,
                granularity=self._granularity,
                endianness=self._endianness,
                value_type=self._value_type,
                sensitivity=self._sensitivity,
                should_cancel=lambda: self._cancel_requested,
            )
        except CandidateInterpretationsCanceled:
            self.canceled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        if self._cancel_requested:
            self.canceled.emit()
            return
        self.finished.emit(items)


class CandidateInterpretationsViewModel(QObject):
    can_ids_changed = QtSignal(list)
    candidate_list_changed = QtSignal(object)
    candidate_detail_changed = QtSignal(dict)
    candidate_plot_changed = QtSignal(object)
    recalculation_started = QtSignal()
    recalculation_finished = QtSignal()
    recalculation_failed = QtSignal(str)
    recalculation_canceled = QtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._df = pl.DataFrame()
        self._mux_configs: list[MuxConfigEntry] = []
        self._checked_ids: set[str] = set()

        self._min_length = 8
        self._max_length = 8
        self._granularity = 8
        self._endianness = "Try Both"
        self._value_type = "Try All"
        self._sensitivity = 50
        self._ts_min: float | None = None
        self._ts_max: float | None = None

        self._items: list[CandidateItem] = []
        self._selected_index = -1
        self._thread: QThread | None = None
        self._worker: _CandidateInterpretationsWorker | None = None

    @property
    def mux_configs(self) -> list[MuxConfigEntry]:
        return list(self._mux_configs)

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        self._df = df if df is not None else pl.DataFrame()
        ids = _sorted_can_ids(self._effective_df())
        self.can_ids_changed.emit(ids)
        if not self._checked_ids:
            self._checked_ids = set(ids)
        else:
            self._checked_ids = {can_id for can_id in self._checked_ids if can_id in ids}
            if not self._checked_ids:
                self._checked_ids = set(ids)
        self._clear_results()

    def set_time_range(self, ts_min: float | None, ts_max: float | None) -> None:
        self._ts_min = ts_min
        self._ts_max = ts_max
        ids = _sorted_can_ids(self._effective_df())
        self.can_ids_changed.emit(ids)
        self._checked_ids = {can_id for can_id in self._checked_ids if can_id in ids}
        if not self._checked_ids:
            self._checked_ids = set(ids)
        self._clear_results()

    def set_checked_ids(self, can_ids: set[str]) -> None:
        normalized = {str(can_id).strip().upper() for can_id in can_ids if str(can_id).strip()}
        if normalized == self._checked_ids:
            return
        self._checked_ids = normalized
        self._clear_results()

    def set_mux_configuration(self, configs: list[MuxConfigEntry]) -> None:
        self._mux_configs = list(configs)
        self._clear_results()

    def set_parameters(
        self,
        *,
        min_length: int,
        max_length: int,
        granularity: int,
        endianness: str,
        value_type: str,
        sensitivity: int,
    ) -> None:
        self._min_length = max(1, min(int(min_length), 64))
        self._max_length = max(1, min(int(max_length), 64))
        if self._max_length < self._min_length:
            self._min_length, self._max_length = self._max_length, self._min_length
        self._granularity = max(1, min(int(granularity), 64))
        self._endianness = endianness
        self._value_type = value_type
        self._sensitivity = max(0, min(int(sensitivity), 100))

    def recalculate(self) -> None:
        if self.running:
            return

        self.recalculation_started.emit()

        self._thread = QThread(self)
        self._worker = _CandidateInterpretationsWorker(
            df=self._effective_df(),
            checked_ids=self._checked_ids,
            mux_configs=self._mux_configs,
            min_length=self._min_length,
            max_length=self._max_length,
            granularity=self._granularity,
            endianness=self._endianness,
            value_type=self._value_type,
            sensitivity=self._sensitivity,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_recalculation_finished)
        self._worker.canceled.connect(self._on_recalculation_canceled)
        self._worker.failed.connect(self._on_recalculation_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.canceled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def cancel_recalculation(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.cancel_recalculation()
            self._thread.quit()
            self._thread.wait(2000)

    def set_selected_candidate_index(self, index: int) -> None:
        index = int(index)
        if index < 0 or index >= len(self._items):
            self._selected_index = -1
            self.candidate_detail_changed.emit({})
            self.candidate_plot_changed.emit([])
            return
        self._selected_index = index
        self._emit_selected_candidate()

    def selected_candidate(self) -> CandidateItem | None:
        if 0 <= self._selected_index < len(self._items):
            return self._items[self._selected_index]
        return None

    def _emit_selected_candidate(self) -> None:
        if self._selected_index < 0 or self._selected_index >= len(self._items):
            self.candidate_detail_changed.emit({})
            self.candidate_plot_changed.emit([])
            return
        item = self._items[self._selected_index]
        self.candidate_detail_changed.emit(
            {
                "Label": item.label,
                "CAN ID": item.can_id,
                "Frame LEN": item.frame_len,
                "MUX": item.mux_label,
                "Signal Length": item.signal_length,
                "Frames": item.frames,
                "Changes": item.changes,
                "Distinct Values": item.distinct_values,
                "Score": f"{item.score:.3f}",
                "Min": "" if item.min_value is None else _format_number(item.min_value),
                "Max": "" if item.max_value is None else _format_number(item.max_value),
                "Sample Values": ", ".join(item.sample_values),
            }
        )
        self.candidate_plot_changed.emit(
            [CandidateSeries(label=item.label, x=list(item.timestamps), y=list(item.values), color="#ff9f1c")]
        )

    def _clear_results(self) -> None:
        self._items = []
        self._selected_index = -1
        self.candidate_list_changed.emit([])
        self.candidate_detail_changed.emit({})
        self.candidate_plot_changed.emit([])

    def _on_recalculation_finished(self, items: list[CandidateItem]) -> None:
        self._items = items
        self.candidate_list_changed.emit(self._items)
        if not self._items:
            self._selected_index = -1
            self.candidate_detail_changed.emit({})
            self.candidate_plot_changed.emit([])
            self.recalculation_finished.emit()
            return
        if self._selected_index < 0 or self._selected_index >= len(self._items):
            self._selected_index = 0
        self._emit_selected_candidate()
        self.recalculation_finished.emit()

    def _on_recalculation_canceled(self) -> None:
        self.recalculation_canceled.emit()
        self.recalculation_finished.emit()

    def _on_recalculation_failed(self, message: str) -> None:
        self.recalculation_failed.emit(message)
        self.recalculation_finished.emit()

    def _cleanup_worker(self) -> None:
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None

    def _effective_df(self) -> pl.DataFrame:
        df = self._df if self._df is not None else pl.DataFrame()
        if df.is_empty() or "TS" not in df.columns:
            return df
        if self._ts_min is not None:
            df = df.filter(pl.col("TS") >= float(self._ts_min))
        if self._ts_max is not None:
            df = df.filter(pl.col("TS") <= float(self._ts_max))
        return df


def _sorted_can_ids(df: pl.DataFrame) -> list[str]:
    if df is None or df.is_empty() or "ID" not in df.columns:
        return []
    return sorted(df["ID"].unique().to_list(), key=can_id_sort_key)
