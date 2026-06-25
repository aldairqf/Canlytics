from __future__ import annotations

import numpy as np


def compute_fft(
    ts: np.ndarray,
    ys: np.ndarray,
    *,
    n_points: int = 4096,
    t_min: float | None = None,
    t_max: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Resample a non-uniform signal to a uniform grid and compute its one-sided FFT.

    Applies a Hann window to reduce spectral leakage.  Returns a corrected
    amplitude spectrum so that a pure sine of amplitude A produces a peak of A.

    Args:
        ts: timestamp array (seconds, non-uniform OK)
        ys: signal value array, same length as ts
        n_points: number of uniform resample points (power-of-2 recommended)
        t_min / t_max: optional range to restrict analysis; uses full range if None

    Returns:
        freqs_hz: frequency axis in Hz, shape (n_points // 2 + 1,)
        magnitudes: amplitude spectrum in the same units as ys
    """
    ts = np.asarray(ts, dtype=float)
    ys = np.asarray(ys, dtype=float)

    valid = np.isfinite(ts) & np.isfinite(ys)
    ts, ys = ts[valid], ys[valid]

    if t_min is not None:
        mask = ts >= t_min
        ts, ys = ts[mask], ys[mask]
    if t_max is not None:
        mask = ts <= t_max
        ts, ys = ts[mask], ys[mask]

    if len(ts) < 4:
        return np.array([0.0]), np.array([0.0])

    duration = float(ts[-1] - ts[0])
    if duration <= 0.0:
        return np.array([0.0]), np.array([0.0])

    t_uniform = np.linspace(ts[0], ts[-1], n_points)
    y_uniform = np.interp(t_uniform, ts, ys)

    window = np.hanning(n_points)
    amplitude_correction = n_points / window.sum()
    y_windowed = y_uniform * window

    fft_result = np.fft.rfft(y_windowed)
    freqs = np.fft.rfftfreq(n_points, d=duration / n_points)

    magnitudes = np.abs(fft_result) * 2.0 / n_points * amplitude_correction
    magnitudes[0] /= 2.0  # DC component is not doubled

    return freqs, magnitudes
