"""Pure logic for Candidate Interpretations' "Value at Time" constraint search.

Extracted from views/candidate_constraint_search.py (BUGS.md B-21): the search itself
used to run synchronously on the GUI thread with no progress/cancel. Qt-free here so
it can run in a worker and be unit-tested without a running app.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Callable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from services.candidate_interpretations import CandidateItem


class ConstraintSearchCanceled(Exception):
    pass


@dataclass(frozen=True)
class Constraint:
    time_abs: float
    target_norm: float  # 0.0-1.0, already clamped
    was_clamped: bool = False  # B-22: True if the raw input was outside [0, 1]


@dataclass(frozen=True)
class ConstraintHit:
    norm_actual: float
    actual: float
    y_min: float
    y_span: float


@dataclass(frozen=True)
class SearchResult:
    item: CandidateItem
    hits: tuple[ConstraintHit, ...]


@dataclass(frozen=True)
class SearchExclusions:
    """B-24: why candidates got excluded, so the UI can show a summary instead of
    silently returning fewer results than the user expected."""
    too_few_samples: int = 0
    zero_variance: int = 0
    no_data_near_constraint: int = 0
    outside_tolerance: int = 0

    @property
    def total(self) -> int:
        return self.too_few_samples + self.zero_variance + self.no_data_near_constraint + self.outside_tolerance


def time_to_abs(
    hours: int, minutes: int, seconds: int, t_min: float, timezone_mode: str, *, day_offset: int = 0,
) -> float:
    """day_offset (B-23): which calendar day, relative to the recording's start, the
    clock time refers to -- without it, a recording crossing midnight can never
    target a time on "day 2"."""
    if timezone_mode in ("none", None, ""):
        return t_min + day_offset * 86400 + hours * 3600 + minutes * 60 + seconds
    try:
        tz = dt_timezone.utc if timezone_mode == "UTC" else ZoneInfo(timezone_mode)
        ref_dt = datetime.fromtimestamp(t_min, dt_timezone.utc).astimezone(tz)
        target_dt = (ref_dt + timedelta(days=day_offset)).replace(
            hour=hours, minute=minutes, second=seconds, microsecond=0
        )
        return target_dt.timestamp()
    except (ZoneInfoNotFoundError, OSError, ValueError):
        return t_min + day_offset * 86400 + hours * 3600 + minutes * 60 + seconds


def normalize(ys: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Return (normalized 0-1, y_min, y_span). If span==0 returns zeros."""
    y_min = float(ys.min())
    y_max = float(ys.max())
    span = y_max - y_min
    if span == 0.0:
        return np.zeros_like(ys), y_min, 0.0
    return (ys - y_min) / span, y_min, span


def clamp_target(raw: float) -> tuple[float, bool]:
    """B-22: returns (clamped value, was_clamped) instead of clamping silently."""
    clamped = max(0.0, min(1.0, raw))
    return clamped, clamped != raw


def search_candidates(
    items: Sequence[CandidateItem],
    constraints: Sequence[Constraint],
    *,
    precision: float,
    tolerance: float,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[SearchResult], SearchExclusions]:
    results: list[SearchResult] = []
    counts = {"too_few_samples": 0, "zero_variance": 0, "no_data_near_constraint": 0, "outside_tolerance": 0}
    total = len(items)

    for done, item in enumerate(items, start=1):
        if should_cancel is not None and should_cancel():
            raise ConstraintSearchCanceled()

        xs = np.array(item.timestamps, dtype=float)
        ys = np.array(item.values, dtype=float)
        if len(xs) < 2:
            counts["too_few_samples"] += 1
            if on_progress is not None:
                on_progress(done, total)
            continue

        y_norm, y_min, y_span = normalize(ys)
        if y_span == 0.0:
            counts["zero_variance"] += 1
            if on_progress is not None:
                on_progress(done, total)
            continue

        hits: list[ConstraintHit] = []
        ok = True
        exclusion_reason: str | None = None
        for constraint in constraints:
            t_abs = constraint.time_abs
            mask = (xs >= t_abs - precision) & (xs <= t_abs + precision)
            if not mask.any():
                ok = False
                exclusion_reason = "no_data_near_constraint"
                break

            if xs[0] <= t_abs <= xs[-1]:
                interp_norm = float(np.interp(t_abs, xs, y_norm))
                interp_actual = float(np.interp(t_abs, xs, ys))
            else:
                w_xs, w_yn, w_ys = xs[mask], y_norm[mask], ys[mask]
                idx = int(np.argmin(np.abs(w_xs - t_abs)))
                interp_norm, interp_actual = float(w_yn[idx]), float(w_ys[idx])

            if abs(interp_norm - constraint.target_norm) > tolerance:
                ok = False
                exclusion_reason = "outside_tolerance"
                break

            hits.append(ConstraintHit(norm_actual=interp_norm, actual=interp_actual, y_min=y_min, y_span=y_span))

        if ok:
            results.append(SearchResult(item=item, hits=tuple(hits)))
        elif exclusion_reason:
            counts[exclusion_reason] += 1
        if on_progress is not None:
            on_progress(done, total)

    return results, SearchExclusions(**counts)
