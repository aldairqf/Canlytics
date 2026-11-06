from __future__ import annotations

import polars as pl
from models.bit_track import BitTrack


class BitStateAccumulator:
    """Retain only state transitions for one raw CAN bit."""

    def __init__(self, track: BitTrack) -> None:
        self.track = track
        self.timestamps: list[float] = []
        self.values: list[int] = []
        self._last_value: int | None = None

    @property
    def last_value(self) -> int | None:
        return self._last_value

    def reset(self, dataframe: pl.DataFrame) -> None:
        self.timestamps.clear()
        self.values.clear()
        self._last_value = None
        self.append(dataframe)

    def append(self, dataframe: pl.DataFrame) -> list[tuple[float, int]]:
        byte_column = f"D{self.track.byte_index}"
        if dataframe.is_empty() or not {"TS", "ID", "LEN", byte_column}.issubset(dataframe.columns):
            return []
        rows = dataframe.filter(
            (pl.col("ID").str.to_uppercase() == self.track.can_id.upper())
            & (pl.col("LEN") > self.track.byte_index)
        ).select("TS", byte_column)
        mask = 1 << self.track.bit_index
        transitions: list[tuple[float, int]] = []
        for timestamp, byte_value in rows.iter_rows():
            value = 1 if int(byte_value) & mask else 0
            if value == self._last_value:
                continue
            self.timestamps.append(float(timestamp))
            self.values.append(value)
            transitions.append((float(timestamp), value))
            self._last_value = value
        return transitions

    def snapshot(self) -> tuple[list[float], list[int]]:
        return list(self.timestamps), list(self.values)
