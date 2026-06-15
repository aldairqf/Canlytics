import numpy as np


def apply_filter(y, filter_type: str | None, filter_params: dict | None):
    y = np.array(y, dtype=float)

    if not filter_type or filter_type in ("None",):
        return y

    params = filter_params or {}

    if filter_type == "Moving Average":
        window = int(params.get("window", 10))
        if window <= 1:
            return y
        kernel = np.ones(window) / window
        y_padded = np.pad(y, (window - 1, 0), mode="edge")
        return np.convolve(y_padded, kernel, mode="valid")

    if filter_type == "Exponential Moving Average":
        alpha = float(params.get("alpha", 0.2))
        if len(y) == 0:
            return y
        out = np.empty_like(y)
        out[0] = y[0]
        for i in range(1, len(y)):
            out[i] = alpha * y[i] + (1 - alpha) * out[i - 1]
        return out

    if filter_type == "Median":
        window = int(params.get("window", 3))
        if window <= 1:
            return y
        y_padded = np.pad(y, (window - 1, 0), mode="edge")
        return np.array(
            [np.median(y_padded[i : i + window]) for i in range(len(y))],
            dtype=float,
        )

    if filter_type == "Gaussian":
        sigma = float(params.get("sigma", 1.0))
        if sigma <= 0:
            return y
        size = int(6 * sigma + 1)
        if size % 2 == 0:
            size += 1
        x = np.arange(size) - size // 2
        kernel = np.exp(-(x**2) / (2 * sigma**2))
        kernel /= kernel.sum()
        y_padded = np.pad(y, (size - 1, 0), mode="edge")
        return np.convolve(y_padded, kernel, mode="valid")

    if filter_type == "Savitzky-Golay":
        window = int(params.get("window", 5))
        polyorder = int(params.get("polyorder", 2))

        if window <= polyorder:
            return y

        y_padded = np.pad(y, (window - 1, 0), mode="edge")

        out = np.empty_like(y)
        x_vals = np.arange(-(window - 1), 1)  # past samples up to current (x=0)

        for i in range(len(y)):
            coeffs = np.polyfit(x_vals, y_padded[i : i + window], polyorder)
            out[i] = np.polyval(coeffs, 0)

        return out

    if filter_type == "Truncate Decimals":
        decimals = int(params.get("decimals", 1))
        decimals = max(0, decimals)
        factor = 10.0 ** decimals
        return np.trunc(y * factor) / factor

    if filter_type == "Round Decimals":
        decimals = int(params.get("decimals", 1))
        decimals = max(0, decimals)
        return np.round(y, decimals=decimals)

    return y
