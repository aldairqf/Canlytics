import numpy as np

# Default max scatter markers per signal (overridable per-signal; also the snap cap).
MARKER_MAX_PTS = 5000


def downsample_series(x, y, max_points: int):
    if max_points <= 0:
        return x, y

    if len(x) <= max_points:
        return x, y

    step = int(np.ceil(len(x) / max_points))
    return x[::step], y[::step]


def visible_downsample(x, y, x_range, max_points: int):
    """Keep points inside the visible x_range, then downsample to max_points."""
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    if xa.size == 0 or x_range is None:
        return downsample_series(xa, ya, max_points)
    lo, hi = (x_range[1], x_range[0]) if x_range[1] < x_range[0] else (x_range[0], x_range[1])
    # Boolean mask (not searchsorted) so it's correct for non-monotonic x too.
    mask = (xa >= lo) & (xa <= hi)
    return downsample_series(xa[mask], ya[mask], max_points)
