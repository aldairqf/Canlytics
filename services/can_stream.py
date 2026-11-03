from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from services.can_data_parser import frame_dict, rows_to_df
from services.can_source import CanSource, SourceFrame
from services.can_sources import ReplayCanSource, SshCanSource


class CanStreamRunner:
    """Apply the shared timestamp, batching, and cancellation policy to a source."""

    def __init__(
        self,
        source: CanSource,
        config: dict[str, Any],
        *,
        canceled: Callable[[], bool],
        status: Callable[[str], None],
        on_chunk: Callable[[Any], None],
        pump_events: Callable[[], None] = lambda: None,
        on_bitrate: Callable[[int], None] = lambda _bitrate: None,
        wall_time: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self._source = source
        self._config = config
        self._canceled = canceled
        self._status = status
        self._on_chunk = on_chunk
        self._pump_events = pump_events
        self._on_bitrate = on_bitrate
        self._wall_time = wall_time
        self._monotonic = monotonic
        self._start_ts: float | None = None

    def run(self) -> None:
        rows: list[dict[str, Any]] = []
        last_flush = self._monotonic()
        try:
            self._source.open(canceled=self._canceled, status=self._status)
            if self._source.bitrate:
                self._on_bitrate(int(self._source.bitrate))
            while not self._canceled():
                self._pump_events()
                frame = self._source.receive(float(self._config.get("poll_timeout", 0.01)))
                if frame is not None and not frame.is_error:
                    rows.append(self._to_row(frame))
                last_flush = self._flush(rows, last_flush)
                if self._source.finished:
                    break
            if rows:
                self._on_chunk(rows_to_df(rows))
            self._status("Stopped")
        finally:
            self._source.close()

    def _to_row(self, frame: SourceFrame) -> dict[str, Any]:
        offset = float(self._config.get("ts_offset", 0.0))
        if isinstance(self._source, ReplayCanSource):
            timestamp = round(float(frame.timestamp or 0.0) + offset, 6)
        else:
            ts_source = str(self._config.get("ts_source", "pc")).lower()
            timestamp = (
                float(frame.timestamp or self._wall_time())
                if ts_source == "device"
                else self._wall_time()
            )
            if bool(self._config.get("normalize")):
                if self._start_ts is None:
                    self._start_ts = timestamp
                timestamp = round(timestamp - self._start_ts, 6)
            timestamp += offset
            if isinstance(self._source, SshCanSource) and ts_source == "device" and offset:
                timestamp = round(timestamp, 6)
        row = frame_dict(
            ts=timestamp,
            bus=frame.bus,
            can_id=frame.can_id,
            data=frame.data,
        )
        if frame.length is not None:
            row["LEN"] = frame.length
        return row

    def _flush(self, rows: list[dict[str, Any]], last_flush: float) -> float:
        now = self._monotonic()
        if rows and (len(rows) >= 200 or now - last_flush >= 0.05):
            self._on_chunk(rows_to_df(rows))
            rows.clear()
            return now
        return last_flush
