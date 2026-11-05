from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal


class TimeCursorViewModel(QObject):
    cursor_changed = Signal(float, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._timestamp: float | None = None
        self._source: str | None = None

    @property
    def timestamp(self) -> float | None:
        return self._timestamp

    def set_timestamp(self, timestamp: float, source: str = "external") -> bool:
        try:
            value = float(timestamp)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
        normalized_source = str(source)
        if value == self._timestamp and normalized_source == self._source:
            return False
        self._timestamp = value
        self._source = normalized_source
        self.cursor_changed.emit(value, normalized_source)
        return True
