from __future__ import annotations

import pyqtgraph as pg

from utils.timezone_format import format_timestamp


class TimeAxisItem(pg.AxisItem):
    def __init__(self, timezone_mode: str = "none", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timezone_mode = timezone_mode
        # Prevent pyqtgraph from appending "(x1e+09)" to the axis label when
        # tick values are large unix timestamps.
        self.enableAutoSIPrefix(False)

    def set_timezone(self, tz: str) -> None:
        self.timezone_mode = tz
        self.picture = None
        self.update()

    def format_value(self, value: float) -> str:
        return format_timestamp(value, self.timezone_mode)

    def tickStrings(self, values, scale, spacing):
        return [format_timestamp(v, self.timezone_mode) for v in values]
