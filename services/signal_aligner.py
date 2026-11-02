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


def align_incremental(
    new_batches: list[tuple[np.ndarray, np.ndarray]],
    last_known: list[float | None],
) -> tuple[np.ndarray, list[np.ndarray], list[float | None]]:
    """Align new samples while carrying each series' value across the watermark."""
    if len(new_batches) != len(last_known):
        raise ValueError("new_batches and last_known must have the same length")
    normalized: list[tuple[np.ndarray, np.ndarray]] = []
    for ts, values in new_batches:
        ts_array = np.asarray(ts, dtype=float).ravel()
        value_array = np.asarray(values, dtype=float).ravel()
        if len(ts_array) != len(value_array):
            raise ValueError("timestamp and value arrays must have the same length")
        normalized.append((ts_array, value_array))

    nonempty_ts = [ts for ts, _ in normalized if ts.size]
    if not nonempty_ts:
        return np.array([], dtype=float), [np.array([], dtype=float) for _ in new_batches], list(last_known)

    common_ts = np.unique(np.concatenate(nonempty_ts))
    aligned: list[np.ndarray] = []
    updated_last = list(last_known)
    for index, (ts, values) in enumerate(normalized):
        if ts.size:
            sample_indexes = np.searchsorted(ts, common_ts, side="right") - 1
            has_sample = sample_indexes >= 0
            out = np.full(common_ts.size, np.nan, dtype=float)
            out[has_sample] = values[sample_indexes[has_sample]]
            if updated_last[index] is not None:
                out[~has_sample] = float(updated_last[index])
            updated_last[index] = float(values[-1])
        else:
            fill = np.nan if updated_last[index] is None else float(updated_last[index])
            out = np.full(common_ts.size, fill, dtype=float)
        aligned.append(out)
    return common_ts, aligned, updated_last
