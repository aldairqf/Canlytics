from __future__ import annotations

import csv
from pathlib import Path

import numpy as np


def align_xy_series(
    x_ts: np.ndarray,
    x_values: np.ndarray,
    y_ts: np.ndarray,
    y_values: np.ndarray,
    *,
    start: float | None = None,
    end: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Align Y to each X timestamp using the latest Y sample at or before it."""
    x_ts = np.asarray(x_ts, dtype=float)
    x_values = np.asarray(x_values, dtype=float)
    y_ts = np.asarray(y_ts, dtype=float)
    y_values = np.asarray(y_values, dtype=float)
    if x_ts.size != x_values.size or y_ts.size != y_values.size:
        raise ValueError("Timestamp and value arrays must have matching lengths")
    x_valid = np.isfinite(x_ts) & np.isfinite(x_values)
    y_valid = np.isfinite(y_ts) & np.isfinite(y_values)
    x_ts, x_values = x_ts[x_valid], x_values[x_valid]
    y_ts, y_values = y_ts[y_valid], y_values[y_valid]
    x_order = np.argsort(x_ts, kind="stable")
    y_order = np.argsort(y_ts, kind="stable")
    x_ts, x_values = x_ts[x_order], x_values[x_order]
    y_ts, y_values = y_ts[y_order], y_values[y_order]
    if start is not None:
        keep = x_ts >= float(start)
        x_ts, x_values = x_ts[keep], x_values[keep]
    if end is not None:
        keep = x_ts <= float(end)
        x_ts, x_values = x_ts[keep], x_values[keep]
    y_idx = np.searchsorted(y_ts, x_ts, side="right") - 1
    matched = y_idx >= 0
    return x_ts[matched], x_values[matched], y_values[y_idx[matched]]


def export_xy_csv(
    path: str | Path,
    timestamps: np.ndarray,
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    x_name: str,
    y_name: str,
) -> None:
    """Write aligned XY samples and their timestamps as UTF-8 CSV."""
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Timestamp (epoch seconds)", x_name, y_name])
        writer.writerows(zip(timestamps, x_values, y_values, strict=True))
