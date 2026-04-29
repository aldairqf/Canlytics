import pyqtgraph as pg
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import math


class TimeAxisItem(pg.AxisItem):
    def __init__(self, timezone_mode="none", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timezone_mode = timezone_mode
        self._tz_cache = None

    def set_timezone(self, tz):
        self.timezone_mode = tz
        self._tz_cache = None
        self.picture = None
        self.update()

    def _get_timezone(self):
        if self._tz_cache is not None:
            return self._tz_cache

        if self.timezone_mode in ("none", None):
            self._tz_cache = None
        elif self.timezone_mode == "UTC":
            self._tz_cache = timezone.utc
        else:
            try:
                self._tz_cache = ZoneInfo(self.timezone_mode)
            except ZoneInfoNotFoundError:
                self._tz_cache = timezone.utc

        return self._tz_cache

    def format_value(self, value: float) -> str:
        tz = self._get_timezone()

        try:
            value = float(value)
            if not math.isfinite(value):
                return ""
        except Exception:
            return ""

        if tz is None:
            return f"{value:.2f}"

        try:
            dt = datetime.fromtimestamp(value, timezone.utc).astimezone(tz)
            return dt.strftime("%H:%M:%S")
        except Exception:
            return ""

    def tickStrings(self, values, scale, spacing):
        labels = []
        for v in values:
            labels.append(self.format_value(v))

        return labels
