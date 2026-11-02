from __future__ import annotations

from dataclasses import dataclass
import math
import time

import polars as pl

from utils.can_id import can_id_sort_key

_STUFFING_ESTIMATE = 1.2


@dataclass(frozen=True)
class CanIdStatistics:
    can_id: str
    frame_count: int
    frames_per_second: float
    period_min: float | None
    period_mean: float | None
    period_max: float | None
    jitter: float | None
    is_new: bool
    is_missing: bool
    periods_reliable: bool


@dataclass(frozen=True)
class BusStatisticsSnapshot:
    frame_count: int
    frames_per_second: float
    estimated_load_percent: float | None
    bitrate: int | None
    can_id_count: int
    active_id_count: int
    can_ids: tuple[CanIdStatistics, ...]
    new_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]


@dataclass
class _CanIdAccumulator:
    frame_count: int = 0
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    last_arrival: float = 0.0
    period_count: int = 0
    period_min: float | None = None
    period_mean: float = 0.0
    period_max: float | None = None
    period_m2: float = 0.0
    is_new: bool = False
    periods_reliable: bool = True

    def ingest(self, timestamps: list[float], arrival: float, is_new: bool) -> None:
        timestamps.sort()
        for timestamp in timestamps:
            if self.last_timestamp is None:
                self.first_timestamp = timestamp
                self.last_timestamp = timestamp
            elif timestamp < self.last_timestamp:
                self.periods_reliable = False
                self.first_timestamp = min(self.first_timestamp, timestamp)
            else:
                if self.periods_reliable:
                    self._add_period(timestamp - self.last_timestamp)
                self.last_timestamp = timestamp
        self.frame_count += len(timestamps)
        self.is_new = self.is_new or is_new
        self.last_arrival = arrival

    def _add_period(self, period: float) -> None:
        self.period_count += 1
        self.period_min = period if self.period_min is None else min(self.period_min, period)
        self.period_max = period if self.period_max is None else max(self.period_max, period)
        delta = period - self.period_mean
        self.period_mean += delta / self.period_count
        self.period_m2 += delta * (period - self.period_mean)

    def snapshot(self, can_id: str, *, now: float, live: bool, timeout_seconds: float) -> CanIdStatistics:
        duration = (
            self.last_timestamp - self.first_timestamp
            if self.last_timestamp is not None and self.first_timestamp is not None else 0.0
        )
        frames_per_second = max(self.frame_count - 1, 0) / duration if duration > 0 else 0.0
        has_periods = self.periods_reliable and self.period_count > 0
        jitter = math.sqrt(self.period_m2 / self.period_count) if has_periods else None
        missing = live and now - self.last_arrival >= timeout_seconds
        return CanIdStatistics(
            can_id=can_id,
            frame_count=self.frame_count,
            frames_per_second=frames_per_second,
            period_min=self.period_min if has_periods else None,
            period_mean=self.period_mean if has_periods else None,
            period_max=self.period_max if has_periods else None,
            jitter=jitter,
            is_new=self.is_new,
            is_missing=missing,
            periods_reliable=self.periods_reliable,
        )


class BusStatisticsAccumulator:
    """Accumulate bus and per-ID statistics from new frame chunks."""

    def __init__(self, *, missing_after_seconds: float = 2.0):
        self.missing_after_seconds = max(float(missing_after_seconds), 0.1)
        self.reset()

    def reset(self) -> None:
        self._ids: dict[str, _CanIdAccumulator] = {}
        self._frame_count = 0
        self._estimated_bits = 0.0
        self._first_timestamp: float | None = None
        self._last_timestamp: float | None = None
        self._buses: set[str] = set()

    def seed(self, dataframe: pl.DataFrame | None) -> None:
        self.reset()
        self.ingest(dataframe, mark_new=False)

    def ingest(
        self,
        dataframe: pl.DataFrame | None,
        *,
        mark_new: bool = True,
        arrival_time: float | None = None,
    ) -> None:
        if dataframe is None or dataframe.is_empty():
            return
        arrival = time.monotonic() if arrival_time is None else float(arrival_time)
        frames_by_id: dict[str, list[float]] = {}
        new_ids: set[str] = set()
        for timestamp, bus, can_id, frame_len in dataframe.select(["TS", "Bus", "ID", "LEN"]).iter_rows():
            normalized_id = str(can_id).upper().removesuffix("X")
            ts = float(timestamp)
            current = self._ids.get(normalized_id)
            if current is None:
                current = _CanIdAccumulator()
                self._ids[normalized_id] = current
                if mark_new:
                    new_ids.add(normalized_id)
            frames_by_id.setdefault(normalized_id, []).append(ts)
            self._frame_count += 1
            self._first_timestamp = ts if self._first_timestamp is None else min(self._first_timestamp, ts)
            self._last_timestamp = ts if self._last_timestamp is None else max(self._last_timestamp, ts)
            self._buses.add(str(bus or "can0"))
            identifier = int(normalized_id, 16)
            base_bits = 67 if identifier > 0x7FF else 47
            self._estimated_bits += math.ceil((base_bits + 8 * int(frame_len)) * _STUFFING_ESTIMATE)
        for can_id, timestamps in frames_by_id.items():
            self._ids[can_id].ingest(timestamps, arrival, can_id in new_ids)

    def snapshot(
        self,
        *,
        bitrate: int | None = None,
        live: bool = False,
        now: float | None = None,
    ) -> BusStatisticsSnapshot:
        current = time.monotonic() if now is None else float(now)
        duration = (
            self._last_timestamp - self._first_timestamp
            if self._last_timestamp is not None and self._first_timestamp is not None else 0.0
        )
        frames_per_second = max(self._frame_count - 1, 0) / duration if duration > 0 else 0.0
        load = None
        if bitrate and bitrate > 0 and duration > 0 and len(self._buses) <= 1:
            load = self._estimated_bits / duration / int(bitrate) * 100.0
        entries = tuple(
            self._ids[can_id].snapshot(
                can_id, now=current, live=live, timeout_seconds=self.missing_after_seconds
            )
            for can_id in sorted(self._ids, key=can_id_sort_key)
        )
        new_ids = tuple(item.can_id for item in entries if item.is_new)
        missing_ids = tuple(item.can_id for item in entries if item.is_missing)
        return BusStatisticsSnapshot(
            frame_count=self._frame_count,
            frames_per_second=frames_per_second,
            estimated_load_percent=load,
            bitrate=bitrate,
            can_id_count=len(entries),
            active_id_count=len(entries) - len(missing_ids) if live else len(entries),
            can_ids=entries,
            new_ids=new_ids,
            missing_ids=missing_ids,
        )
