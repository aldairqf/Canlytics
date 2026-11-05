from __future__ import annotations

import math

import numpy as np
import polars as pl

from services.realtime_analysis import REAL_TIME_SCHEMA


class OfflineRealtimeIndex:
    """Index sorted CAN frames for per-ID snapshots at a timestamp."""

    def __init__(self, dataframe: pl.DataFrame | None):
        source = dataframe if dataframe is not None else pl.DataFrame(schema={"TS": pl.Float64, "ID": pl.Utf8})
        if source.is_empty() or "TS" not in source.columns or "ID" not in source.columns:
            self._timestamps: np.ndarray = np.array([], dtype=np.float64)
            self._positions = self._timestamps
            self._groups: dict[str, tuple[pl.DataFrame, np.ndarray]] = {}
            return
        ordered = source.filter(pl.col("TS").is_finite()).sort("TS", maintain_order=True)
        self._timestamps = ordered.get_column("TS").to_numpy()
        self._positions = np.unique(self._timestamps)
        self._groups = {}
        for group in ordered.partition_by("ID", maintain_order=True):
            can_id = str(group.get_column("ID")[0] or "").strip().upper()
            if can_id:
                self._groups[can_id] = (group, group.get_column("TS").to_numpy())

    @property
    def frame_count(self) -> int:
        return int(self._timestamps.size)

    @property
    def position_count(self) -> int:
        return int(self._positions.size)

    @property
    def first_timestamp(self) -> float | None:
        return float(self._timestamps[0]) if self.frame_count else None

    @property
    def last_timestamp(self) -> float | None:
        return float(self._timestamps[-1]) if self.frame_count else None

    def timestamp_at(self, position_index: int) -> float | None:
        if not self.position_count:
            return None
        index = max(0, min(int(position_index), self.position_count - 1))
        return float(self._positions[index])

    def index_at(self, timestamp: float) -> int:
        if not self.position_count:
            return -1
        value = float(timestamp)
        if not math.isfinite(value):
            return -1
        if value < self._positions[0]:
            return -1
        return min(int(np.searchsorted(self._positions, value, side="right")) - 1, self.position_count - 1)

    def snapshot_at(self, timestamp: float) -> pl.DataFrame:
        try:
            value = float(timestamp)
        except (TypeError, ValueError):
            return self._empty_frame()
        if not math.isfinite(value) or not self._groups:
            return self._empty_frame()
        rows: list[dict] = []
        for group, timestamps in self._groups.values():
            index = int(np.searchsorted(timestamps, value, side="right")) - 1
            if index < 0:
                continue
            row = group.row(index, named=True)
            previous_ts = float(timestamps[index - 1]) if index else None
            row["Delta T"] = round(float(timestamps[index]) - previous_ts, 6) if previous_ts is not None else None
            row["_ChangedBytes"] = ""
            rows.append(row)
        return pl.DataFrame(rows, schema=REAL_TIME_SCHEMA, orient="row") if rows else self._empty_frame()

    @staticmethod
    def _empty_frame() -> pl.DataFrame:
        return pl.DataFrame({key: [] for key in REAL_TIME_SCHEMA}, schema=REAL_TIME_SCHEMA)
