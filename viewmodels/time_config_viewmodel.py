from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QObject, Signal as QtSignal
from zoneinfo import available_timezones


class TimeConfigViewModel(QObject):
    normalize_changed = QtSignal(bool)
    timezone_changed = QtSignal(str)

    def __init__(self, *, normalize: bool, timezone: str, parent: QObject | None = None):
        super().__init__(parent)
        self._normalize = bool(normalize)
        self._timezone = timezone if timezone else "none"
        if self._normalize:
            self._timezone = "none"

    @property
    def normalize(self) -> bool:
        return self._normalize

    @property
    def timezone(self) -> str:
        return self._timezone

    def apply(self, *, normalize: bool, timezone: str) -> None:
        normalize = bool(normalize)
        timezone = timezone if timezone else "none"
        if normalize:
            timezone = "none"

        norm_changed = normalize != self._normalize
        tz_changed = timezone != self._timezone

        self._normalize = normalize
        self._timezone = timezone

        if norm_changed:
            self.normalize_changed.emit(self._normalize)
        if tz_changed:
            self.timezone_changed.emit(self._timezone)

    @staticmethod
    def list_timezones() -> list[str]:
        zones = sorted(available_timezones())
        if "UTC" in zones:
            zones.remove("UTC")
            zones.insert(0, "UTC")
        return zones
