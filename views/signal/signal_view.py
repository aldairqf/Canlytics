# gui/view_signal.py

from PySide6.QtGui import QColor
from core.signal import Signal


class ViewSignal:
    def __init__(
        self,
        signal,
        color,
        line_style,
        line_width,
        filter_type=None,
        filter_params=None,
    ):
        self.signal = signal
        self.color = color
        self.line_style = line_style
        self.line_width = line_width

        self.filter_type = filter_type
        self.filter_params = filter_params or {}
