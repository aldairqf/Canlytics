from __future__ import annotations

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from services.bit_activity import BitActivityAccumulator, BitActivityCanceled


class BitActivityWorker(QObject):
    finished = QtSignal(object)
    canceled = QtSignal()
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(self, dataframe: pl.DataFrame) -> None:
        super().__init__()
        self._dataframe = dataframe
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        accumulator = BitActivityAccumulator()
        try:
            accumulator.seed(
                self._dataframe,
                should_cancel=lambda: self._cancel_requested,
                on_progress=self.progress.emit,
            )
        except BitActivityCanceled:
            self.canceled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if self._cancel_requested:
            self.canceled.emit()
            return
        self.finished.emit(accumulator)
