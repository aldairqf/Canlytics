from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, Signal as QtSignal

from models.analysis_context import AnalysisMarker
from services.session_state import SessionStateStore
from services.event_markers import (
    EventComparison,
    append_event_marker,
    build_event_comparisons,
    normalize_event_markers,
    session_marker_key,
)


class EventMarkersViewModel(QObject):
    markers_changed = QtSignal(object)

    def __init__(self, session_state: SessionStateStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._session_state = session_state
        self._source_paths: tuple[str, ...] = ()
        self._session_key = ""
        self._markers: tuple[AnalysisMarker, ...] = ()

    @property
    def markers(self) -> tuple[AnalysisMarker, ...]:
        return self._markers

    @property
    def session_key(self) -> str:
        return self._session_key

    def set_session_sources(self, source_paths: Sequence[str]) -> None:
        normalized_paths = tuple(sorted({
            str(Path(path).expanduser().resolve())
            for path in source_paths
            if str(path).strip()
        }))
        new_key = session_marker_key(normalized_paths)
        if new_key == self._session_key:
            return
        if self._session_key and normalized_paths and set(self._source_paths).issubset(normalized_paths):
            if self._markers and not self._session_state.get_event_markers(new_key):
                self._session_state.set_event_markers(new_key, self._serialize(self._markers))
        self._source_paths = normalized_paths
        self._session_key = new_key
        self._markers = normalize_event_markers(self._session_state.get_event_markers(new_key))
        self.markers_changed.emit(self._markers)

    def add_marker(self, name: str, state: str, timestamp: float) -> AnalysisMarker:
        if not self._session_key:
            raise ValueError("load or start a session before adding event markers")
        self._markers = append_event_marker(self._markers, name, state, timestamp)
        marker = self._markers[-1]
        self._session_state.set_event_markers(self._session_key, self._serialize(self._markers))
        self.markers_changed.emit(self._markers)
        return marker

    def comparisons(self, log_start: float, log_end: float) -> tuple[EventComparison, ...]:
        return build_event_comparisons(self._markers, log_start=log_start, log_end=log_end)

    def shift_timestamps(self, delta: float) -> None:
        if not self._markers or not delta:
            return
        self._markers = tuple(
            AnalysisMarker(
                sequence=marker.sequence,
                name=marker.name,
                timestamp=marker.timestamp + delta,
                state=marker.state,
            )
            for marker in self._markers
        )
        self._session_state.set_event_markers(self._session_key, self._serialize(self._markers))
        self.markers_changed.emit(self._markers)

    def clear_markers(self) -> None:
        self._markers = ()
        if self._session_key:
            self._session_state.set_event_markers(self._session_key, [])
        self.markers_changed.emit(self._markers)

    def context_markers(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "sequence": marker.sequence,
                "name": marker.name,
                "timestamp": marker.timestamp,
                "state": marker.state,
            }
            for marker in self._markers
        )

    @staticmethod
    def _serialize(markers: Sequence[AnalysisMarker]) -> list[dict[str, object]]:
        return [
            {
                "sequence": marker.sequence,
                "name": marker.name,
                "timestamp": marker.timestamp,
                "state": marker.state,
            }
            for marker in markers
        ]
