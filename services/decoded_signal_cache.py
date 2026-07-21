"""Incremental cache of decoded (ts, y) numpy arrays, keyed by an opaque signature."""

from __future__ import annotations

import numpy as np


class DecodedSignalCache:
    def __init__(self) -> None:
        # Chunks stay unconcatenated until get() actually needs the merged view --
        # same lazy-concat pattern as AnalyzeDataAccumulator's _ts_chunks/_d_chunks.
        # extend() used to np.concatenate the WHOLE history on every single call
        # (one per incoming streaming chunk); when multiple extends land between
        # two redraws (plot_window.py's 200ms redraw coalescing), this collapsed
        # what used to be N full-history copies into a single concat at get() time.
        self._chunks: dict[tuple, list[tuple[np.ndarray, np.ndarray]]] = {}
        self._materialized: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}

    def get(self, key: tuple) -> tuple[np.ndarray, np.ndarray] | None:
        if key not in self._chunks:
            return None
        cached = self._materialized.get(key)
        if cached is not None:
            return cached
        ts_chunks, y_chunks = zip(*self._chunks[key])
        ts = ts_chunks[0] if len(ts_chunks) == 1 else np.concatenate(ts_chunks)
        y = y_chunks[0] if len(y_chunks) == 1 else np.concatenate(y_chunks)
        merged = (ts, y)
        self._materialized[key] = merged
        return merged

    def set_full(self, key: tuple, ts: np.ndarray, y: np.ndarray) -> None:
        self._chunks[key] = [(ts, y)]
        self._materialized[key] = (ts, y)

    def extend(self, key: tuple, new_ts: np.ndarray, new_y: np.ndarray) -> None:
        """Append onto whatever's cached for *key*, or seed a fresh entry."""
        if new_ts.size == 0:
            return
        self._chunks.setdefault(key, []).append((new_ts, new_y))
        self._materialized.pop(key, None)

    def clear(self) -> None:
        self._chunks.clear()
        self._materialized.clear()

    def __contains__(self, key: tuple) -> bool:
        return key in self._chunks

    def __len__(self) -> int:
        return len(self._chunks)
