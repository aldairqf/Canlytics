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

    def tickStrings(self, values, scale, spacing):
        tz = self._get_timezone()

        labels = []
        for v in values:
            try:
                v = float(v)
                if not math.isfinite(v):
                    labels.append("")
                    continue
            except Exception:
                labels.append("")
                continue

            if tz is None:
                labels.append(f"{v:.2f}")
                continue

            try:
                dt = datetime.fromtimestamp(v, timezone.utc).astimezone(tz)
                labels.append(dt.strftime("%H:%M:%S"))
            except Exception:
                labels.append("")

        return labels
