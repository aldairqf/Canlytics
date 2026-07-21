from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal as QtSignal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from config.theme import get_active_theme
from utils.timezone_format import format_timestamp

_HANDLE_PX = 6.0  # grab width, in pixels, for dragging a band's start/end edge
_AXIS_HEIGHT_PX = 18.0  # reserved strip at the bottom for time-axis tick labels
_AXIS_TICK_COUNT = 5


class RangeTimeline(QWidget):
    """Frame-density histogram with two draggable A/B bands to pick the compare windows."""

    range_a_changed = QtSignal(float, float)
    range_b_changed = QtSignal(float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(int(72 + _AXIS_HEIGHT_PX))
        self.setMouseTracking(True)
        self._edges: list[float] = []
        self._counts: list[int] = []
        self._span_min = 0.0
        self._span_max = 1.0
        self._range_a = (0.0, 0.0)
        self._range_b = (0.0, 0.0)
        self._timezone_mode: str | None = None
        self._drag: tuple[str, str] | None = None  # (band, "start"|"end"|"move")
        self._drag_anchor_px = 0.0
        self._drag_anchor_value = (0.0, 0.0)

    def set_density(self, edges: list[float], counts: list[int]) -> None:
        self._edges = list(edges)
        self._counts = list(counts)
        if len(self._edges) >= 2:
            self._span_min, self._span_max = self._edges[0], self._edges[-1]
        self.update()

    def set_timezone(self, tz_mode: str | None) -> None:
        self._timezone_mode = tz_mode
        self.update()

    def set_range_a(self, start: float, end: float) -> None:
        self._range_a = (start, end)
        self.update()

    def set_range_b(self, start: float, end: float) -> None:
        self._range_b = (start, end)
        self.update()

    def _value_to_x(self, value: float) -> float:
        span = self._span_max - self._span_min
        if span <= 0:
            return 0.0
        return (value - self._span_min) / span * self.width()

    def _x_to_value(self, x: float) -> float:
        span = self._span_max - self._span_min
        if span <= 0:
            return self._span_min
        ratio = max(0.0, min(1.0, x / max(1.0, float(self.width()))))
        return self._span_min + ratio * span

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = get_active_theme()
        painter.fillRect(self.rect(), QColor(theme.surface))
        self._paint_histogram(painter, theme)
        self._paint_band(painter, self._range_a, theme.accent, "A")
        self._paint_band(painter, self._range_b, theme.error, "B")
        self._paint_time_axis(painter, theme)
        painter.end()

    def _content_height(self) -> float:
        return max(1.0, self.height() - _AXIS_HEIGHT_PX)

    def _paint_histogram(self, painter: QPainter, theme) -> None:
        if not self._counts:
            return
        max_count = max(self._counts) or 1
        color = QColor(theme.text_muted)
        n = len(self._counts)
        bar_w = self.width() / n
        h = self._content_height()
        for i, count in enumerate(self._counts):
            bar_h = (count / max_count) * (h - 4)
            painter.fillRect(QRectF(i * bar_w, h - bar_h, max(1.0, bar_w - 1), bar_h), color)

    def _paint_band(self, painter: QPainter, rng: tuple[float, float], color_hex: str, label: str) -> None:
        h = self._content_height()
        x0, x1 = sorted((self._value_to_x(rng[0]), self._value_to_x(rng[1])))
        color = QColor(color_hex)
        fill = QColor(color)
        fill.setAlpha(70)
        painter.fillRect(QRectF(x0, 0, max(2.0, x1 - x0), h), fill)
        pen = QPen(color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(QPointF(x0, 0), QPointF(x0, h))
        painter.drawLine(QPointF(x1, 0), QPointF(x1, h))
        painter.drawText(QPointF(x0 + 4, 14), label)

    def _paint_time_axis(self, painter: QPainter, theme) -> None:
        # BUGS.md / user feedback 2026-07-19: the bar had no visible time reference at
        # all -- ticks respect the configured timezone via the same formatter used
        # for the A/B fields and the plot's own time axis.
        if self._span_max <= self._span_min:
            return
        content_h = self._content_height()
        axis_top = content_h
        pen = QPen(QColor(theme.text_muted))
        painter.setPen(pen)
        painter.drawLine(QPointF(0, axis_top), QPointF(self.width(), axis_top))
        span = self._span_max - self._span_min
        for i in range(_AXIS_TICK_COUNT):
            frac = i / (_AXIS_TICK_COUNT - 1)
            value = self._span_min + frac * span
            x = frac * self.width()
            painter.drawLine(QPointF(x, axis_top), QPointF(x, axis_top + 4))
            label = format_timestamp(value, self._timezone_mode)
            text_x = max(2.0, min(x - 28, self.width() - 58))
            painter.drawText(QPointF(text_x, self.height() - 4), label)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        hit = self._hit_test(event.position().x())
        if hit is None:
            return
        band, mode = hit
        self._drag = (band, mode)
        self._drag_anchor_px = event.position().x()
        self._drag_anchor_value = self._range_a if band == "a" else self._range_b

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is None:
            return
        band, mode = self._drag
        x = event.position().x()
        value = self._x_to_value(x)
        start, end = self._drag_anchor_value

        if mode == "start":
            start = min(value, end)
        elif mode == "end":
            end = max(value, start)
        else:
            shift = value - self._x_to_value(self._drag_anchor_px)
            start, end = start + shift, end + shift

        if band == "a":
            self._range_a = (start, end)
            self.range_a_changed.emit(start, end)
        else:
            self._range_b = (start, end)
            self.range_b_changed.emit(start, end)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag = None

    def _hit_test(self, x: float) -> tuple[str, str] | None:
        # "b" checked first -- it's painted last, so it visually sits on top.
        for band, rng in (("b", self._range_b), ("a", self._range_a)):
            x0, x1 = sorted((self._value_to_x(rng[0]), self._value_to_x(rng[1])))
            if abs(x - x0) <= _HANDLE_PX:
                return band, "start"
            if abs(x - x1) <= _HANDLE_PX:
                return band, "end"
            if x0 < x < x1:
                return band, "move"
        return None
