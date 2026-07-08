from __future__ import annotations

from uuid import uuid4

from PySide6.QtGui import QColor

from models.frame_selector import FrameSelector
from models.signal import Signal
from utils.plot_sampling import MARKER_MAX_PTS


class ViewSignal:
    def __init__(
        self,
        signal: Signal,
        color: QColor,
        line_style,
        line_width,
        *,
        selector: FrameSelector | None = None,
        filter_type=None,
        filter_params=None,
        internal_id: str | None = None,
        marker_enabled: bool = False,
        marker_shape: str = "Circle",
        marker_size: int = 8,
        marker_color: QColor | None = None,
        marker_border_color: QColor | None = None,
        marker_border_width: int = 1,
        value_format: str = "auto",
        value_decimals: int = 6,
        value_unit: str = "",
        step_mode: bool = False,
        visible: bool = True,
        marker_max_points: int = MARKER_MAX_PTS,
    ):
        self.signal = signal
        self.selector = selector or FrameSelector()
        self.color = color
        self.line_style = line_style
        self.line_width = line_width
        self.filter_type = filter_type
        self.filter_params = filter_params or {}
        self.internal_id = str(internal_id or uuid4().hex)
        self.marker_enabled = bool(marker_enabled)
        self.marker_shape = marker_shape or "Circle"
        self.marker_size = int(marker_size)
        self.marker_color = marker_color or QColor(color)
        self.marker_border_color = marker_border_color or QColor(color)
        self.marker_border_width = int(marker_border_width)
        self.value_format = str(value_format or "auto")
        self.value_decimals = int(value_decimals)
        self.value_unit = str(value_unit or "")
        self.step_mode = bool(step_mode)
        self.visible = bool(visible)
        self.marker_max_points = int(marker_max_points)
