from __future__ import annotations

from PySide6.QtGui import QColor

from models.frame_selector import FrameSelector
from models.signal import Signal


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
    ):
        self.signal = signal
        self.selector = selector or FrameSelector()
        self.color = color
        self.line_style = line_style
        self.line_width = line_width
        self.filter_type = filter_type
        self.filter_params = filter_params or {}
