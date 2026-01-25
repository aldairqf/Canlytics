import numpy as np


def downsample_series(x, y, max_points: int):
    if max_points <= 0:
        return x, y

    if len(x) <= max_points:
        return x, y

    step = int(np.ceil(len(x) / max_points))
    return x[::step], y[::step]
