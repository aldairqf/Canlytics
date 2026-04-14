from __future__ import annotations

from typing import Any

import polars as pl
from PySide6.QtCore import QObject, Signal

from services.mux_detector import MuxDetectorConfig, detect_mux_candidates


class MuxDetectionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        df: pl.DataFrame,
        selected_groups: list[tuple[str, int]],
        config: MuxDetectorConfig,
    ):
        super().__init__()
        self._df = df
        self._selected_groups = selected_groups
        self._config = config

    def run(self) -> None:
        try:
            results: list[dict[str, Any]] = []
            for can_id, frame_len in self._selected_groups:
                candidate_map = detect_mux_candidates(self._df, can_id=can_id, cfg=self._config)
                candidates = candidate_map.get(int(frame_len), [])
                results.append(
                    {
                        "can_id": can_id,
                        "frame_len": int(frame_len),
                        "label": f"{can_id} | LEN {int(frame_len)}",
                        "candidates": candidates,
                    }
                )
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
