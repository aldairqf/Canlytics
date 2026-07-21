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


def minmax_downsample(x, y, max_points: int):
    """Bucket-based min/max decimation: unlike downsample_series()'s naive stride
    (x[::step]), every bucket contributes both its local min and max, so a brief
    spike (a value that changes for only one or a few samples) can never fall
    between the sampled points and vanish -- the standard technique dashboards use
    for a one-shot, non-interactive summary plot (Grafana/InfluxDB/TradingView all
    do bucketed min/max, not naive striding, for exactly this reason). Use this for
    static overviews (e.g. Matrix sparklines); downsample_series() is fine where the
    user can zoom into full resolution afterward (the main interactive plot)."""
    x = np.asarray(x)
    y = np.asarray(y)
    n = len(x)
    if max_points <= 0 or n <= max_points:
        return x, y

    buckets = max(1, max_points // 2)
    bucket_size = int(np.ceil(n / buckets))
    xs_out = []
    ys_out = []
    for start in range(0, n, bucket_size):
        bx = x[start : start + bucket_size]
        by = y[start : start + bucket_size]
        if by.size == 0:
            continue
        min_idx = int(np.argmin(by))
        max_idx = int(np.argmax(by))
        if min_idx == max_idx:
            xs_out.append(bx[min_idx])
            ys_out.append(by[min_idx])
        elif min_idx < max_idx:
            xs_out.extend((bx[min_idx], bx[max_idx]))
            ys_out.extend((by[min_idx], by[max_idx]))
        else:
            xs_out.extend((bx[max_idx], bx[min_idx]))
            ys_out.extend((by[max_idx], by[min_idx]))
    return np.array(xs_out), np.array(ys_out)


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
