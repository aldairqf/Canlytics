from __future__ import annotations

import math
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Sequence

import numpy as np
import polars as pl

from models.frame_selector import FrameSelector
from models.signal import Signal

CorrelationMethod = Literal["pearson", "spearman"]
_MAX_LAG_STEPS = 10_000
_MAX_INTERPOLATION_GAP_FACTOR = 3.0


@dataclass(frozen=True)
class CorrelationWindow:
    start: float
    end: float
    coefficient: float
    samples: int


@dataclass(frozen=True)
class CorrelationResult:
    method: CorrelationMethod
    coefficient: float
    lag_seconds: float
    scale: float
    offset: float
    samples: int
    windows: tuple[CorrelationWindow, ...]


@dataclass(frozen=True)
class TimedSeries:
    name: str
    timestamps: tuple[float, ...]
    values: tuple[float, ...]


@dataclass(frozen=True)
class ReferenceSource:
    kind: Literal["csv", "dbc", "candidate", "markers"]
    name: str
    path: str = ""
    dbc_name: str = ""
    message_name: str = ""
    signal_name: str = ""
    candidate_label: str = ""


class CorrelationCanceled(Exception):
    pass


def load_reference_csv(path: str | Path) -> TimedSeries:
    """Load a two-column CSV; prefer conventional time and value header names."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.reader(stream) if row and any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("reference CSV needs at least 3 time/value samples")
    has_header = True
    try:
        float(rows[0][0])
        float(rows[0][1])
        has_header = False
    except (ValueError, IndexError):
        pass
    header = [cell.strip().casefold() for cell in rows[0]] if has_header else []
    time_index = next((i for i, name in enumerate(header) if name in {"time", "timestamp", "ts", "seconds"}), 0)
    value_index = next((i for i, name in enumerate(header) if name in {"value", "signal", "reference"}), 1)
    timestamps: list[float] = []
    values: list[float] = []
    data_rows = rows[1:] if has_header else rows
    for row in data_rows:
        if max(time_index, value_index) >= len(row):
            continue
        try:
            timestamps.append(float(row[time_index]))
            values.append(float(row[value_index]))
        except ValueError:
            continue
    if len(timestamps) < 3:
        raise ValueError("reference CSV needs at least 3 numeric time/value samples")
    return TimedSeries(Path(path).stem, tuple(timestamps), tuple(values))


def event_marker_reference(
    candidate_times: Sequence[float], markers: Sequence[dict], name: str
) -> TimedSeries:
    """Sample named ON/OFF markers as a binary reference over candidate timestamps."""
    selected = sorted(
        (marker for marker in markers if str(marker.get("name", "")) == name),
        key=lambda marker: (float(marker["timestamp"]), int(marker["sequence"])),
    )
    ordered_indices = sorted(range(len(candidate_times)), key=lambda index: float(candidate_times[index]))
    values = [0.0] * len(candidate_times)
    marker_index = 0
    active = False
    for index in ordered_indices:
        timestamp = float(candidate_times[index])
        while marker_index < len(selected) and float(selected[marker_index]["timestamp"]) <= timestamp:
            active = str(selected[marker_index].get("state", "")).upper() == "ON"
            marker_index += 1
        values[index] = 1.0 if active else 0.0
    return TimedSeries(name, tuple(float(value) for value in candidate_times), tuple(values))


def resolve_reference_series(
    source: ReferenceSource,
    *,
    candidate_times: Sequence[float],
    dataframe: pl.DataFrame,
    dbc_manager: object,
    candidates: Sequence[object],
    markers: Sequence[dict],
) -> TimedSeries:
    """Resolve a selected CSV, DBC signal, candidate, or event-marker reference."""
    if source.kind == "csv":
        return load_reference_csv(source.path)
    if source.kind == "markers":
        return event_marker_reference(candidate_times, markers, source.name)
    if source.kind == "candidate":
        selected = next((item for item in candidates if item.label == source.candidate_label), None)
        if selected is None:
            raise ValueError("selected candidate reference is no longer available")
        return TimedSeries(selected.label, tuple(selected.timestamps), tuple(selected.values))
    if source.kind == "dbc":
        definition = dbc_manager.get_signal_definition(
            source.dbc_name, source.message_name, source.signal_name
        )
        signal = Signal(
            name=str(definition["name"]),
            can_id=str(definition["can_id"]),
            start_bit=int(definition["start_bit"]),
            length=int(definition["length"]),
            le=bool(definition["le"]),
            scale=float(definition["scale"]),
            offset=float(definition["offset"]),
            mux_start=int(definition["mux_start"]),
            mux_bytes=int(definition["mux_bytes"]),
            mux_value=definition["mux_value"],
            type_data=str(definition["type_data"]),
        )
        selector = FrameSelector(
            selected_id=signal.can_id,
            mode=definition["id_match"],
            pgn=definition["pgn"],
        )
        from services.can_decoder import decode_signal

        timestamps, values = decode_signal(dataframe, signal, selector)
        if not timestamps:
            raise ValueError("DBC reference has no samples in the loaded log")
        return TimedSeries(source.signal_name, tuple(timestamps), tuple(values))
    raise ValueError(f"unsupported reference source: {source.kind}")


def correlate_reference(
    candidate_times: Sequence[float],
    candidate_values: Sequence[float],
    reference_times: Sequence[float],
    reference_values: Sequence[float],
    *,
    method: CorrelationMethod = "spearman",
    window_seconds: float = 5.0,
    max_lag_seconds: float = 2.0,
    lag_step_seconds: float = 0.05,
    min_samples_per_window: int = 5,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> CorrelationResult:
    """Align two timed series, score each lag by temporal windows, and fit reference units."""
    if method not in ("pearson", "spearman"):
        raise ValueError("method must be 'pearson' or 'spearman'")
    window = _positive_finite(window_seconds, "window_seconds")
    max_lag = _finite_nonnegative(max_lag_seconds, "max_lag_seconds")
    lag_step = _positive_finite(lag_step_seconds, "lag_step_seconds")
    minimum = int(min_samples_per_window)
    if minimum < 3:
        raise ValueError("min_samples_per_window must be at least 3")
    lag_steps = int(math.ceil((2.0 * max_lag / lag_step) - 1e-12)) + 1
    if lag_steps > _MAX_LAG_STEPS:
        raise ValueError(f"lag search cannot exceed {_MAX_LAG_STEPS} steps")

    candidate_t, candidate_y = _clean_series(candidate_times, candidate_values, "candidate")
    reference_t, reference_y = _clean_series(reference_times, reference_values, "reference")
    start = float(candidate_t[0])
    window_ids = np.floor((candidate_t - start) / window).astype(np.int64)
    lags = _lag_grid(max_lag, lag_step)

    best: tuple[float, float, list[CorrelationWindow], np.ndarray, np.ndarray] | None = None
    total_lags = int(lags.size)
    for lag_index, lag in enumerate(lags, start=1):
        if should_cancel and should_cancel():
            raise CorrelationCanceled()
        if on_progress is not None:
            on_progress(lag_index, total_lags)
        query_times = candidate_t + lag
        inside = (query_times >= reference_t[0]) & (query_times <= reference_t[-1])
        inside &= _interpolation_supported(reference_t, query_times)
        if int(inside.sum()) < minimum:
            continue
        aligned_candidate = candidate_y[inside]
        aligned_reference = np.interp(query_times[inside], reference_t, reference_y)
        aligned_windows = window_ids[inside]
        windows: list[CorrelationWindow] = []
        aggregate_values: list[tuple[float, int]] = []
        fit_candidate: list[np.ndarray] = []
        fit_reference: list[np.ndarray] = []
        for window_id in np.unique(aligned_windows):
            selected = aligned_windows == window_id
            count = int(selected.sum())
            if count < minimum:
                continue
            coefficient = _correlation(
                aligned_candidate[selected], aligned_reference[selected], method
            )
            if coefficient is None:
                continue
            window_start = start + float(window_id) * window
            windows.append(
                CorrelationWindow(
                    start=window_start,
                    end=window_start + window,
                    coefficient=coefficient,
                    samples=count,
                )
            )
            aggregate_values.append((coefficient, count))
            fit_candidate.append(aligned_candidate[selected])
            fit_reference.append(aligned_reference[selected])
        if not aggregate_values:
            continue
        score = _weighted_correlation(aggregate_values)
        candidate = (
            score,
            float(lag),
            windows,
            np.concatenate(fit_candidate),
            np.concatenate(fit_reference),
        )
        if best is None or _better_lag(candidate, best):
            best = candidate

    if best is None:
        raise ValueError("no lag has enough variable samples in any complete window")
    coefficient, lag, windows, aligned_candidate, aligned_reference = best
    scale, offset = _linear_fit(aligned_candidate, aligned_reference)
    return CorrelationResult(
        method=method,
        coefficient=coefficient,
        lag_seconds=lag,
        scale=_round_significant(scale, 4),
        offset=_round_significant(offset, 4),
        samples=int(aligned_candidate.size),
        windows=tuple(windows),
    )


def _clean_series(
    timestamps: Sequence[float], values: Sequence[float], label: str
) -> tuple[np.ndarray, np.ndarray]:
    times = np.asarray(timestamps, dtype=float)
    samples = np.asarray(values, dtype=float)
    if times.ndim != 1 or samples.ndim != 1 or times.size != samples.size:
        raise ValueError(f"{label} timestamps and values must be one-dimensional and equal length")
    valid = np.isfinite(times) & np.isfinite(samples)
    if int(valid.sum()) < 3:
        raise ValueError(f"{label} series needs at least 3 finite samples")
    times = times[valid]
    samples = samples[valid]
    order = np.argsort(times, kind="stable")
    times = times[order]
    samples = samples[order]
    unique_times, inverse, counts = np.unique(times, return_inverse=True, return_counts=True)
    if unique_times.size != times.size:
        samples = np.bincount(inverse, weights=samples) / counts
        times = unique_times
    if times.size < 3:
        raise ValueError(f"{label} series needs at least 3 distinct timestamps")
    return times, samples


def _lag_grid(maximum: float, step: float) -> np.ndarray:
    if maximum == 0:
        return np.array([0.0])
    steps = int(math.floor((maximum / step) + 1e-12))
    regular = np.arange(-steps, steps + 1, dtype=float) * step
    endpoints = np.array([-maximum, 0.0, maximum], dtype=float)
    return np.unique(np.round(np.concatenate((regular, endpoints)), decimals=12))


def _interpolation_supported(reference_times: np.ndarray, query_times: np.ndarray) -> np.ndarray:
    """Avoid inventing samples across gaps much larger than the reference cadence."""
    intervals = np.diff(reference_times)
    typical_interval = float(np.median(intervals))
    right = np.searchsorted(reference_times, query_times, side="left")
    exact = np.zeros(query_times.shape, dtype=bool)
    in_range = right < reference_times.size
    exact[in_range] = reference_times[right[in_range]] == query_times[in_range]
    between = (right > 0) & in_range & ~exact
    supported = exact.copy()
    if np.any(between):
        left_indices = right[between] - 1
        gaps = reference_times[right[between]] - reference_times[left_indices]
        supported[between] = gaps <= typical_interval * _MAX_INTERPOLATION_GAP_FACTOR
    return supported


def _correlation(left: np.ndarray, right: np.ndarray, method: CorrelationMethod) -> float | None:
    if method == "spearman":
        left, right = _rankdata(left), _rankdata(right)
    left_delta = left - float(np.mean(left))
    right_delta = right - float(np.mean(right))
    denominator = float(np.linalg.norm(left_delta) * np.linalg.norm(right_delta))
    if denominator <= np.finfo(float).eps:
        return None
    return float(np.clip(np.dot(left_delta, right_delta) / denominator, -1.0, 1.0))


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    ranks = np.empty(values.size, dtype=float)
    index = 0
    while index < values.size:
        end = index + 1
        while end < values.size and sorted_values[end] == sorted_values[index]:
            end += 1
        ranks[order[index:end]] = (index + end - 1) / 2.0 + 1.0
        index = end
    return ranks


def _weighted_correlation(entries: Sequence[tuple[float, int]]) -> float:
    weighted_z: list[float] = []
    weights: list[int] = []
    for coefficient, count in entries:
        clipped = float(np.clip(coefficient, -0.999999, 0.999999))
        weight = max(1, count - 3)
        weighted_z.append(math.atanh(clipped) * weight)
        weights.append(weight)
    return math.tanh(sum(weighted_z) / sum(weights))


def _linear_fit(candidate: np.ndarray, reference: np.ndarray) -> tuple[float, float]:
    centered = candidate - float(np.mean(candidate))
    variance = float(np.dot(centered, centered))
    if variance <= np.finfo(float).eps:
        raise ValueError("candidate samples are constant at the selected lag")
    scale = float(np.dot(centered, reference - float(np.mean(reference))) / variance)
    offset = float(np.mean(reference) - scale * np.mean(candidate))
    return scale, offset


def _round_significant(value: float, digits: int) -> float:
    if value == 0 or not math.isfinite(value):
        return value
    places = digits - int(math.floor(math.log10(abs(value)))) - 1
    return round(value, places)


def _better_lag(candidate: tuple, current: tuple) -> bool:
    candidate_score, candidate_lag = candidate[:2]
    current_score, current_lag = current[:2]
    if abs(candidate_score) > abs(current_score) + 1e-12:
        return True
    if abs(abs(candidate_score) - abs(current_score)) <= 1e-12:
        return abs(candidate_lag) < abs(current_lag)
    return False


def _positive_finite(value: float, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{label} must be positive and finite")
    return result


def _finite_nonnegative(value: float, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return result
