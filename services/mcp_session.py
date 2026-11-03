from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import asdict, is_dataclass
from typing import Iterable

import polars as pl

from config.app_config import get_option


class McpSessionSnapshot:
    """Thread-safe, bounded view of the app session for local MCP requests."""

    def __init__(self, *, frame_capacity: int | None = None, max_query_frames: int | None = None):
        self._frame_capacity = int(
            frame_capacity if frame_capacity is not None else get_option("mcp_session_frame_buffer", 5000)
        )
        if self._frame_capacity < 1:
            raise ValueError("frame_capacity must be positive")
        self._max_query_frames = int(
            max_query_frames if max_query_frames is not None else get_option("mcp_session_max_frames_per_query", 500)
        )
        if self._max_query_frames < 1:
            raise ValueError("mcp_session_max_frames_per_query must be positive")
        self._max_query_frames = min(self._max_query_frames, self._frame_capacity)
        self._lock = threading.RLock()
        self._frames: deque[dict] = deque(maxlen=self._frame_capacity)
        self._frame_count = 0
        self._can_ids: tuple[str, ...] = ()
        self._source_paths: tuple[str, ...] = ()
        self._connection_running = False
        self._connection_mode = "offline"
        self._unsaved_capture = False
        self._last_timestamp: float | None = None
        self._context: dict | None = None
        self._markers: list[dict] = []

    @property
    def max_query_frames(self) -> int:
        return self._max_query_frames

    def replace_dataframe(
        self,
        dataframe: pl.DataFrame | None,
        *,
        can_ids: Iterable[str],
        source_paths: Iterable[str],
        unsaved: bool,
        connection_running: bool,
    ) -> None:
        """Replace the session snapshot after load, clear, normalize, or reorder."""
        with self._lock:
            self._frames.clear()
            if dataframe is not None and not dataframe.is_empty():
                self._frames.extend(self._frame_dict(row) for row in dataframe.tail(self._frame_capacity).iter_rows(named=True))
                self._frame_count = dataframe.height
                self._last_timestamp = float(dataframe["TS"].max())
            else:
                self._frame_count = 0
                self._last_timestamp = None
            self._can_ids = self._sort_can_ids(can_ids)
            self._source_paths = tuple(sorted({str(path) for path in source_paths}))
            self._unsaved_capture = bool(unsaved)
            self._connection_running = bool(connection_running)

    def append_rows(
        self,
        dataframe: pl.DataFrame,
        *,
        can_ids: Iterable[str],
        source_paths: Iterable[str],
        total_frames: int,
        unsaved: bool,
        connection_running: bool,
    ) -> None:
        """Append one already-merged delta without scanning the historical dataframe."""
        if dataframe.is_empty():
            return
        rows = [self._frame_dict(row) for row in dataframe.iter_rows(named=True)]
        with self._lock:
            self._frames.extend(rows)
            self._frame_count = int(total_frames)
            self._can_ids = self._sort_can_ids(can_ids)
            self._source_paths = tuple(sorted({str(path) for path in source_paths}))
            self._unsaved_capture = bool(unsaved)
            self._connection_running = bool(connection_running)
            latest = max(float(row["TS"]) for row in rows)
            self._last_timestamp = max(self._last_timestamp or latest, latest)

    def set_connection_running(self, running: bool) -> None:
        with self._lock:
            self._connection_running = bool(running)
            self._connection_mode = "live" if running else "offline"

    def set_connection_mode(self, mode: str) -> None:
        if mode not in {"offline", "live", "replay"}:
            raise ValueError("connection mode must be offline, live, or replay")
        with self._lock:
            self._connection_mode = mode
            self._connection_running = mode != "offline"

    def set_unsaved_capture(self, unsaved: bool) -> None:
        with self._lock:
            self._unsaved_capture = bool(unsaved)

    def set_analysis_context(self, context: object | None) -> None:
        with self._lock:
            if context is None:
                self._context = None
            elif is_dataclass(context):
                self._context = asdict(context)
            elif isinstance(context, dict):
                self._context = dict(context)
            else:
                raise TypeError("analysis context must be a dataclass or dict")

    def get_analysis_context(self) -> dict | None:
        with self._lock:
            return dict(self._context) if self._context is not None else None

    def get_open_session(self) -> dict:
        with self._lock:
            return {
                "data_loaded": bool(self._frame_count or self._source_paths),
                "frame_count": self._frame_count,
                "can_ids": list(self._can_ids),
                "source_paths": list(self._source_paths),
                "connection_running": self._connection_running,
                "connection_mode": self._connection_mode,
                "unsaved_capture": self._unsaved_capture,
                "last_timestamp": self._last_timestamp,
                "buffered_frames": len(self._frames),
                "frame_buffer_capacity": self._frame_capacity,
            }

    def get_recent_frames(
        self,
        *,
        limit: int = 100,
        can_id: str | None = None,
        ts_min: float | None = None,
        ts_max: float | None = None,
    ) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self._max_query_frames:
            raise ValueError(f"limit must be between 1 and {self._max_query_frames}")
        if ts_min is not None and not math.isfinite(float(ts_min)):
            raise ValueError("ts_min must be finite")
        if ts_max is not None and not math.isfinite(float(ts_max)):
            raise ValueError("ts_max must be finite")
        if ts_min is not None and ts_max is not None and ts_min > ts_max:
            raise ValueError("ts_min must be less than or equal to ts_max")
        normalized_id = self._normalize_can_id(can_id) if can_id is not None else None
        with self._lock:
            candidates = [
                frame for frame in reversed(self._frames)
                if (normalized_id is None or frame["ID"] == normalized_id)
                and (ts_min is None or frame["TS"] >= float(ts_min))
                and (ts_max is None or frame["TS"] <= float(ts_max))
            ][:limit]
            frames = list(reversed(candidates))
            return {
                "frames": frames,
                "returned": len(frames),
                "buffered_frames": len(self._frames),
                "frame_count": self._frame_count,
                "buffer_truncated": self._frame_count > len(self._frames),
            }

    def add_session_marker(self, name: str, *, timestamp: float | None = None) -> dict:
        clean_name = str(name or "").strip()
        if not clean_name or len(clean_name) > 120:
            raise ValueError("marker name must contain between 1 and 120 characters")
        with self._lock:
            if timestamp is None:
                if self._last_timestamp is None:
                    raise ValueError("timestamp is required when the session has no frames")
                selected_timestamp = self._last_timestamp
            else:
                selected_timestamp = float(timestamp)
                if not math.isfinite(selected_timestamp):
                    raise ValueError("timestamp must be finite")
            marker = {
                "sequence": len(self._markers) + 1,
                "name": clean_name,
                "timestamp": selected_timestamp,
            }
            self._markers.append(marker)
            return dict(marker)

    def list_session_markers(self) -> list[dict]:
        with self._lock:
            return [dict(marker) for marker in self._markers]

    @staticmethod
    def _frame_dict(row: dict) -> dict:
        return {
            "TS": float(row["TS"]),
            "Bus": str(row["Bus"]),
            "ID": str(row["ID"]).upper(),
            "LEN": int(row["LEN"]),
            "DATA": str(row["DATA"]).upper(),
        }

    @staticmethod
    def _normalize_can_id(value: str) -> str:
        text = str(value).strip().upper().removeprefix("0X")
        if not text or any(char not in "0123456789ABCDEF" for char in text):
            raise ValueError(f"Invalid hexadecimal CAN ID: {value}")
        return text

    @staticmethod
    def _sort_can_ids(can_ids: Iterable[str]) -> tuple[str, ...]:
        normalized = {McpSessionSnapshot._normalize_can_id(can_id) for can_id in can_ids}
        return tuple(sorted(normalized, key=lambda value: int(value, 16)))
