from __future__ import annotations

import numpy as np


def interval_statistics(
    timestamps: np.ndarray,
    values: np.ndarray,
    start: float,
    end: float,
) -> tuple[int, float | None, float | None, float | None]:
    """Return count, mean, minimum, and maximum for samples in an inclusive interval."""
    timestamps = np.asarray(timestamps, dtype=float)
    values = np.asarray(values, dtype=float)
    if timestamps.size != values.size:
        raise ValueError("Timestamp and value arrays must have matching lengths")
    if start > end:
        start, end = end, start
    left = int(np.searchsorted(timestamps, start, side="left"))
    right = int(np.searchsorted(timestamps, end, side="right"))
    selected = values[left:right]
    selected = selected[np.isfinite(selected)]
    if selected.size == 0:
        return 0, None, None, None
    return (
        int(selected.size),
        float(selected.mean()),
        float(selected.min()),
        float(selected.max()),
    )
