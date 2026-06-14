from __future__ import annotations

from typing import Any

import polars as pl
from PySide6.QtCore import QObject, Signal as QtSignal

from services.mux_detector import MuxDetectorConfig, detect_fast_mux_patterns


class MuxDetectionWorker(QObject):
    finished = QtSignal(object)
    failed = QtSignal(str)

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
            grouped_frame_lengths: dict[str, set[int]] = {}
            for can_id, frame_len in self._selected_groups:
                grouped_frame_lengths.setdefault(str(can_id), set()).add(int(frame_len))

            for can_id, frame_lengths in grouped_frame_lengths.items():
                analysis_map = detect_fast_mux_patterns(self._df, can_id=can_id, cfg=self._config)
                for frame_len in sorted(frame_lengths):
                    analysis = analysis_map.get(int(frame_len))
                    results.append(
                        {
                            "can_id": can_id,
                            "frame_len": int(frame_len),
                            "label": f"{can_id} | LEN {int(frame_len)}",
                            "analysis": None if analysis is None else analysis.to_dict(),
                        }
                    )
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
