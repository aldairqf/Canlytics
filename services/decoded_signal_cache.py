"""Incremental cache of decoded (ts, y) numpy arrays, keyed by an opaque signature."""

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
        """Append onto whatever's cached for *key*, or seed a fresh entry."""
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
