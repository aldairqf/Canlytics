from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from services.candidate_interpretations import CandidateItem


@dataclass(frozen=True)
class CorrelatedCandidate:
    item: CandidateItem
    coefficient: float
    samples: int


@dataclass(frozen=True)
class CandidateCorrelationCluster:
    representative: CandidateItem
    members: tuple[CorrelatedCandidate, ...]


@dataclass(frozen=True)
class _PreparedSeries:
    timestamps: np.ndarray
    values: np.ndarray
    cadence: float
    large_gap_starts: np.ndarray
    large_gap_ends: np.ndarray


class CandidateCorrelationCanceled(Exception):
    pass


def cluster_correlated_candidates(
    candidates: Sequence[CandidateItem],
    *,
    threshold: float = 0.95,
    min_samples: int = 12,
    max_points: int = 500,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[CandidateCorrelationCluster]:
    """Cluster visible candidates whose contemporaneous Spearman correlation is strong."""
    if not np.isfinite(threshold) or not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")
    if min_samples < 3:
        raise ValueError("min_samples must be at least 3")
    if max_points < min_samples:
        raise ValueError("max_points must be at least min_samples")
    ordered = sorted(candidates, key=lambda item: item.score, reverse=True)
    total = len(ordered)
    total_pairs = total * (total - 1) // 2
    total_work = total + total_pairs
    done_work = 0
    prepared: list[_PreparedSeries | None] = []
    for item in ordered:
        _check_canceled(should_cancel)
        prepared.append(_prepare(item, min_samples, max_points))
        done_work += 1
        if on_progress is not None:
            on_progress(done_work, total_work)
    claimed: set[int] = set()
    clusters: list[CandidateCorrelationCluster] = []
    processed_pairs = 0
    for index, representative in enumerate(ordered):
        _check_canceled(should_cancel)
        pair_start = processed_pairs
        if index in claimed or prepared[index] is None:
            processed_pairs += total - index - 1
            done_work += processed_pairs - pair_start
            if on_progress is not None:
                on_progress(done_work, total_work)
            continue
        members: list[CorrelatedCandidate] = []
        for other_index in range(index + 1, total):
            _check_canceled(should_cancel)
            processed_pairs += 1
            if other_index in claimed or prepared[other_index] is None:
                continue
            other = ordered[other_index]
            if _overlapping_interpretation(representative, other):
                continue
            aligned = _align_pair(prepared[index], prepared[other_index], min_samples, max_points)
            if aligned is None:
                continue
            coefficient, sample_count = aligned
            if abs(coefficient) < threshold:
                continue
            claimed.add(other_index)
            members.append(CorrelatedCandidate(other, coefficient, sample_count))
        if members:
            clusters.append(CandidateCorrelationCluster(representative, tuple(members)))
            claimed.add(index)
        done_work += processed_pairs - pair_start
        if on_progress is not None:
            on_progress(done_work, total_work)
    return clusters


def _prepare(
    item: CandidateItem,
    min_samples: int,
    max_points: int,
) -> _PreparedSeries | None:
    timestamps = np.asarray(item.timestamps, dtype=float)
    values = np.asarray(item.values, dtype=float)
    if timestamps.size != values.size:
        return None
    finite = np.isfinite(timestamps) & np.isfinite(values)
    timestamps, values = timestamps[finite], values[finite]
    if timestamps.size < min_samples:
        return None
    order = np.argsort(timestamps, kind="stable")
    timestamps, values = timestamps[order], values[order]
    unique, inverse, counts = np.unique(timestamps, return_inverse=True, return_counts=True)
    if unique.size != timestamps.size:
        values = np.bincount(inverse, weights=values) / counts
        timestamps = unique
    if timestamps.size < min_samples or np.ptp(values) <= np.finfo(float).eps:
        return None
    gaps = np.diff(timestamps)
    cadence = float(np.median(gaps))
    if not np.isfinite(cadence) or cadence <= 0.0:
        return None
    large_gap_indices = np.flatnonzero(gaps > cadence * 3.0)
    large_gap_starts = timestamps[large_gap_indices]
    large_gap_ends = timestamps[large_gap_indices + 1]
    if timestamps.size > max_points:
        required = np.unique(np.concatenate((large_gap_indices, large_gap_indices + 1, [0, timestamps.size - 1])))
        if required.size > max_points:
            return None
        optional_count = max_points - required.size
        regular = np.linspace(0, timestamps.size - 1, num=optional_count, dtype=int) if optional_count else np.array([], dtype=int)
        indices = np.unique(np.concatenate((required, regular)))
        timestamps, values = timestamps[indices], values[indices]
    return _PreparedSeries(timestamps, values, cadence, large_gap_starts, large_gap_ends)


def _align_pair(
    left: _PreparedSeries | None,
    right: _PreparedSeries | None,
    min_samples: int,
    max_points: int,
) -> tuple[float, int] | None:
    if left is None or right is None:
        return None
    left_times, left_values = left.timestamps, left.values
    right_times, right_values = right.timestamps, right.values
    start = max(float(left_times[0]), float(right_times[0]))
    end = min(float(left_times[-1]), float(right_times[-1]))
    if end <= start:
        return None
    left_step = left.cadence
    right_step = right.cadence
    step = max(left_step, right_step)
    if not np.isfinite(step) or step <= 0.0:
        return None
    point_count = min(max_points, int(np.floor(((end - start) / step) + 1e-9)) + 1)
    if point_count < min_samples:
        return None
    grid = np.linspace(start, end, point_count)
    supported = _supported(left, grid) & _supported(right, grid)
    if int(supported.sum()) < min_samples:
        return None
    left_aligned = np.interp(grid[supported], left_times, left_values)
    right_aligned = np.interp(grid[supported], right_times, right_values)
    coefficient = _spearman(left_aligned, right_aligned)
    if coefficient is None:
        return None
    return coefficient, int(supported.sum())


def _supported(series: _PreparedSeries, query: np.ndarray) -> np.ndarray:
    timestamps = series.timestamps
    right = np.searchsorted(timestamps, query, side="left")
    in_range = right < timestamps.size
    exact = np.zeros(query.size, dtype=bool)
    exact[in_range] = timestamps[right[in_range]] == query[in_range]
    between = (right > 0) & in_range & ~exact
    supported = exact.copy()
    if np.any(between):
        left = right[between] - 1
        supported[between] = True
        if series.large_gap_starts.size:
            previous_gap = np.searchsorted(series.large_gap_starts, query[between], side="right") - 1
            has_previous = previous_gap >= 0
            crosses_large_gap = np.zeros(previous_gap.size, dtype=bool)
            crosses_large_gap[has_previous] = (
                query[between][has_previous] < series.large_gap_ends[previous_gap[has_previous]]
            )
            supported[between] &= ~crosses_large_gap
    return supported


def _spearman(left: np.ndarray, right: np.ndarray) -> float | None:
    left_ranks, right_ranks = _rankdata(left), _rankdata(right)
    left_centered = left_ranks - float(left_ranks.mean())
    right_centered = right_ranks - float(right_ranks.mean())
    denominator = float(np.linalg.norm(left_centered) * np.linalg.norm(right_centered))
    if denominator <= np.finfo(float).eps:
        return None
    return float(np.clip(np.dot(left_centered, right_centered) / denominator, -1.0, 1.0))


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


def _overlapping_interpretation(left: CandidateItem, right: CandidateItem) -> bool:
    if left.can_id != right.can_id:
        return False
    if left.frame_len != right.frame_len or left.mux_label != right.mux_label:
        return True
    left_end = left.start_bit + left.signal_length
    right_end = right.start_bit + right.signal_length
    return left.start_bit < right_end and right.start_bit < left_end


def _check_canceled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise CandidateCorrelationCanceled()
