from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from models.analysis_context import AnalysisMarker, TimeRange

MAX_EVENT_NAME_LENGTH = 120


@dataclass(frozen=True)
class EventComparison:
    name: str
    range_a: TimeRange
    range_b: TimeRange
    on_sequence: int
    off_sequence: int


def session_marker_key(source_paths: Sequence[str]) -> str:
    normalized = {
        os.path.normcase(str(Path(path).expanduser().resolve()))
        for path in source_paths
        if str(path).strip()
    }
    return "\n".join(sorted(normalized))


def append_event_marker(
    markers: Sequence[AnalysisMarker], name: str, state: str, timestamp: float
) -> tuple[AnalysisMarker, ...]:
    clean_name = str(name or "").strip()
    clean_state = str(state or "").strip().upper()
    selected_timestamp = float(timestamp)
    if not clean_name or len(clean_name) > MAX_EVENT_NAME_LENGTH:
        raise ValueError("event name must contain between 1 and 120 characters")
    if clean_state not in ("ON", "OFF"):
        raise ValueError("event state must be ON or OFF")
    if not math.isfinite(selected_timestamp):
        raise ValueError("event timestamp must be finite")
    normalized = normalize_event_markers(markers)
    sequence = max((marker.sequence for marker in normalized), default=0) + 1
    return (*normalized, AnalysisMarker(sequence, clean_name, selected_timestamp, clean_state))


def normalize_event_markers(markers: Sequence[AnalysisMarker | dict]) -> tuple[AnalysisMarker, ...]:
    return tuple(_coerce_marker(item) for item in markers)


def build_event_comparisons(
    markers: Sequence[AnalysisMarker], *, log_start: float, log_end: float
) -> tuple[EventComparison, ...]:
    start_bound = float(log_start)
    end_bound = float(log_end)
    if not math.isfinite(start_bound) or not math.isfinite(end_bound) or start_bound > end_bound:
        raise ValueError("log bounds must be finite and ordered")
    pending: dict[str, AnalysisMarker] = {}
    comparisons: list[EventComparison] = []
    ordered = sorted(normalize_event_markers(markers), key=lambda marker: (marker.timestamp, marker.sequence))
    for marker in ordered:
        if marker.state == "ON":
            pending[marker.name] = marker
            continue
        if marker.state != "OFF":
            continue
        on_marker = pending.pop(marker.name, None)
        if on_marker is None or marker.timestamp <= on_marker.timestamp:
            continue
        event_start = max(start_bound, on_marker.timestamp)
        event_end = min(end_bound, marker.timestamp)
        if event_end <= event_start:
            continue
        duration = event_end - event_start
        baseline_start = max(start_bound, event_start - duration)
        baseline_end = math.nextafter(event_start, -math.inf)
        if baseline_end <= baseline_start:
            continue
        comparisons.append(
            EventComparison(
                name=on_marker.name,
                range_a=(baseline_start, baseline_end),
                range_b=(event_start, event_end),
                on_sequence=on_marker.sequence,
                off_sequence=marker.sequence,
            )
        )
    comparisons.sort(key=lambda comparison: (comparison.range_b[1], comparison.off_sequence))
    return tuple(comparisons)


def _coerce_marker(marker: AnalysisMarker | dict) -> AnalysisMarker:
    if isinstance(marker, AnalysisMarker):
        result = marker
    elif isinstance(marker, dict):
        result = AnalysisMarker(
            sequence=int(marker["sequence"]),
            name=str(marker["name"]),
            timestamp=float(marker["timestamp"]),
            state=str(marker["state"]).upper() if marker.get("state") is not None else None,
        )
    else:
        raise TypeError("event markers must be AnalysisMarker instances or dictionaries")
    if result.sequence < 1 or not result.name.strip() or not math.isfinite(result.timestamp):
        raise ValueError("event markers need a positive sequence, name, and finite timestamp")
    if result.state not in ("ON", "OFF"):
        raise ValueError("event marker state must be ON or OFF")
    return AnalysisMarker(result.sequence, result.name.strip(), float(result.timestamp), result.state)
