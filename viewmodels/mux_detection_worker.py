from __future__ import annotations

import threading

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from services.mux_detector import MuxDetectorConfig, detect_muxes


class MuxDetectionWorker(QObject):
    finished = QtSignal(object)
    failed = QtSignal(str)
    progress = QtSignal(int, int)

    def __init__(self, *, df: pl.DataFrame, can_ids: list[str] | None, config: MuxDetectorConfig,
                 forced_selectors: dict[str, tuple[int, ...]] | None = None):
        super().__init__()
        self._df = df
        self._can_ids = can_ids
        self._config = config
        self._forced_selectors = forced_selectors
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            results = detect_muxes(self._df, self._can_ids, self._config, self.progress.emit,
                                   self._cancel.is_set, self._forced_selectors)
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
