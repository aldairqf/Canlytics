from __future__ import annotations

import numpy as np


def align(
    *series: tuple[np.ndarray, np.ndarray],
) -> tuple[np.ndarray, list[np.ndarray]]:
    """Align multiple (ts, y) time series onto a common timestamp axis.

    The common axis is the sorted union of all input timestamps.
    Missing values between samples are filled with the last known value
    (forward-fill / zero-order-hold), which matches CAN bus semantics.

    Parameters
    ----------
    *series:
        Any number of ``(timestamps, values)`` pairs.  Both arrays must be
        1-D and of equal length.  ``ts`` values must be non-decreasing.

    Returns
    -------
    common_ts : np.ndarray
        Sorted union of all input timestamps.
    aligned : list[np.ndarray]
        One aligned value array per input series, evaluated on ``common_ts``.
    """
    if not series:
        return np.array([]), []

    # Build common time axis
    all_ts = np.concatenate([np.asarray(ts, dtype=float) for ts, _ in series])
    common_ts = np.unique(all_ts)

    aligned: list[np.ndarray] = []
    for ts, y in series:
        ts = np.asarray(ts, dtype=float)
        y = np.asarray(y, dtype=float)

        if len(ts) == 0:
            aligned.append(np.full(len(common_ts), np.nan))
            continue

        # For each common timestamp, find the index of the last known sample
        # (searchsorted gives the insertion point; -1 clamps to first sample)
        idx = np.searchsorted(ts, common_ts, side="right") - 1
        idx = np.clip(idx, 0, len(y) - 1)

        out = y[idx]
        # Timestamps before the first sample of this series → NaN
        out = out.astype(float)
        out[common_ts < ts[0]] = np.nan

        aligned.append(out)

    return common_ts, aligned
