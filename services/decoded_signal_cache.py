"""Pure incremental cache of decoded (ts, y) numpy arrays, keyed by an opaque
signature (PlotViewModel uses a signal's decode configuration).

PlotViewModel thin-wraps this so a growing live log's decode cost is O(new
rows) per batch (append the newly-decoded chunk's arrays onto what's already
cached) instead of O(rows accumulated so far) (re-decoding the signal's
entire history from the accumulated dataframe on every batch).
"""

from __future__ import annotations

import numpy as np


class DecodedSignalCache:
    def __init__(self) -> None:
        self._entries: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}

    def get(self, key: tuple) -> tuple[np.ndarray, np.ndarray] | None:
        return self._entries.get(key)

    def set_full(self, key: tuple, ts: np.ndarray, y: np.ndarray) -> None:
        self._entries[key] = (ts, y)

    def extend(self, key: tuple, new_ts: np.ndarray, new_y: np.ndarray) -> None:
        """Append newly-decoded points onto whatever's cached for *key*, or
        seed a fresh entry if nothing was cached yet (e.g. a chunk arrived
        before this signal was ever fully decoded)."""
        if new_ts.size == 0:
            return
        existing = self._entries.get(key)
        if existing is None:
            self._entries[key] = (new_ts, new_y)
            return
        old_ts, old_y = existing
        self._entries[key] = (
            np.concatenate([old_ts, new_ts]),
            np.concatenate([old_y, new_y]),
        )

    def clear(self) -> None:
        self._entries.clear()

    def __contains__(self, key: tuple) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)
