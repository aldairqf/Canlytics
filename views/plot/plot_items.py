import pyqtgraph as pg
from PySide6.QtCore import Qt


def downsample(x, y, step=1):
    if step <= 1:
        return x, y

    return x[::step], y[::step]


class SelectableScatter(pg.ScatterPlotItem):
    def __init__(self, label: str, on_select, on_context, **kwargs):
        super().__init__(**kwargs)
        self._label = label
        self._on_select = on_select
        self._on_context = on_context

    def mouseClickEvent(self, ev):
        if self.pointsAt(ev.pos()).size == 0:
            ev.ignore()
            return

        if ev.button() == Qt.LeftButton:
            ev.accept()
            self._on_select(self._label)
            return

        if ev.button() == Qt.RightButton:
            ev.accept()
            self._on_context()
            return

        ev.ignore()


class ClickableViewBox(pg.ViewBox):
    def __init__(self, on_left_click, on_right_click, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_left_click = on_left_click
        self._on_right_click = on_right_click

    def mouseClickEvent(self, ev):
        if ev.isAccepted():
            return

        if ev.button() == Qt.LeftButton:
            ev.accept()
            self._on_left_click()
            return

        if ev.button() == Qt.RightButton:
            ev.accept()
            self._on_right_click()
            return

        super().mouseClickEvent(ev)
