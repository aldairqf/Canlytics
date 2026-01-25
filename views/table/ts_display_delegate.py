from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PySide6.QtWidgets import QStyledItemDelegate


class TsDisplayDelegate(QStyledItemDelegate):
    def __init__(self, timezone_mode: str = "none", parent=None):
        super().__init__(parent)
        self._timezone_mode = (timezone_mode or "none").strip() or "none"

    def set_timezone_mode(self, tz: str) -> None:
        self._timezone_mode = (tz or "none").strip() or "none"

    def displayText(self, value, locale) -> str:
        tz = self._timezone_mode
        if tz == "none" or value is None:
            return super().displayText(value, locale)

        dt = self._to_datetime(value, tz)
        if dt is None:
            return super().displayText(value, locale)

        ms = dt.microsecond // 1000
        return dt.strftime("%Y-%m-%d %H:%M:%S") + f".{ms:03d}"

    def _to_datetime(self, value, tz: str) -> datetime | None:
        zone = ZoneInfo(tz)

        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(zone)

        if isinstance(value, (int, float)):
            seconds = self._normalize_epoch_seconds(float(value))
            return datetime.fromtimestamp(seconds, tz=zone)

        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            try:
                seconds = self._normalize_epoch_seconds(float(s))
                return datetime.fromtimestamp(seconds, tz=zone)
            except ValueError:
                pass
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(zone)
            except ValueError:
                return None

        return None

    def _normalize_epoch_seconds(self, v: float) -> float:
        av = abs(v)
        if av > 1e18:
            return v / 1e9
        if av > 1e15:
            return v / 1e6
        if av > 1e12:
            return v / 1e3
        return v
