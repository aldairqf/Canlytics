from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from utils.plot_sampling import downsample_series

_MAX_POINTS = 120


class SparklineWidget(QWidget):
    """Small-multiple plot cell: one custom-painted polyline instead of a full
    pg.PlotWidget (each of which is its own QGraphicsView/Scene) -- a grid of a
    hundred-plus cells needs the lightweight sparkline pattern real dashboards use
    for overview grids, not a hundred-plus independent interactive charts."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._x: list[float] = []
        self._y: list[float] = []
        self._color = "#1E74E6"
        self.setAttribute(Qt.WA_NoSystemBackground, False)

    def set_series(self, x, y, color: str) -> None:
        dx, dy = downsample_series(x, y, _MAX_POINTS)
        self._x = list(dx)
        self._y = list(dy)
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if len(self._x) < 2:
            painter.end()
            return
        rect = self.rect()
        x_min, x_max = min(self._x), max(self._x)
        y_min, y_max = min(self._y), max(self._y)
        x_span = (x_max - x_min) or 1.0
        y_span = (y_max - y_min) or 1.0
        pad = 4
        w = rect.width() - 2 * pad
        h = rect.height() - 2 * pad
        points = [
            QPointF(
                pad + (px - x_min) / x_span * w,
                pad + h - (py - y_min) / y_span * h,
            )
            for px, py in zip(self._x, self._y)
        ]
        pen = QPen(QColor(self._color))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawPolyline(points)
        painter.end()
