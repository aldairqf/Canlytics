from PySide6.QtCore import Qt
import pyqtgraph as pg

from .plot_items import SelectableScatter, downsample


class ClickableLegendLabel(pg.LabelItem):
    def __init__(self, text: str, signal_name: str, on_double_click):
        super().__init__(text)
        self.signal_name = signal_name
        self.on_double_click = on_double_click

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.on_double_click(self.signal_name)
            ev.accept()
        else:
            ev.ignore()


class PlotRenderer:
    def __init__(self, plot_widget: pg.PlotWidget, on_select, on_context, on_edit):
        self.plot = plot_widget
        self._items: dict[str, tuple[pg.PlotDataItem, SelectableScatter]] = {}
        self._on_select = on_select
        self._on_context = on_context
        self._on_edit = on_edit
        self.legend = None
        self._needs_autorange = True

    def request_autorange(self):
        self._needs_autorange = True
        self.plot.enableAutoRange()

    def lock_autorange(self):
        self._needs_autorange = False
        self.plot.getViewBox().disableAutoRange()

    def clear(self):
        self.plot.clear()
        self._items.clear()
        self.legend = None
        self._needs_autorange = True

    def render(self, plot_data):
        vb = self.plot.getViewBox()

        if self.legend is None:
            self.legend = self.plot.addLegend(offset=(10, 10))

        pen_style = {
            "Solid": Qt.SolidLine,
            "Dashed": Qt.DashLine,
            "Dotted": Qt.DotLine,
        }

        x_range, y_range = vb.viewRange()

        alive = set()

        for data in plot_data:
            name = data["label"]
            alive.add(name)

            pen = pg.mkPen(
                color=data["style"]["color"],
                width=data["style"]["width"],
                style=pen_style.get(data["style"]["style"], Qt.SolidLine),
            )

            if name in self._items:
                curve, scatter = self._items[name]
                curve.setPen(pen)
                curve.setData(data["x"], data["y"])

                sx, sy = downsample(data["x"], data["y"])
                scatter.setData(x=sx, y=sy)
            else:
                curve = pg.PlotDataItem(data["x"], data["y"], pen=pen)
                curve.setCurveClickable(False)
                curve.setAcceptHoverEvents(False)

                sx, sy = downsample(data["x"], data["y"])
                scatter = SelectableScatter(
                    label=name,
                    on_select=self._on_select,
                    on_context=self._on_context,
                    x=sx,
                    y=sy,
                    size=14,
                    pen=None,
                    brush=(0, 0, 0, 0),
                    hoverable=True,
                )

                self.plot.addItem(curve)
                self.plot.addItem(scatter)

                sample = pg.graphicsItems.LegendItem.ItemSample(curve)
                label = ClickableLegendLabel(
                    text=name,
                    signal_name=name,
                    on_double_click=self._on_legend_double_click,
                )

                row = len(self.legend.items)
                self.legend.items.append((sample, label))
                self.legend.layout.addItem(sample, row, 0)
                self.legend.layout.addItem(label, row, 1)

                self._items[name] = (curve, scatter)

        for name in list(self._items.keys()):
            if name in alive:
                continue

            curve, scatter = self._items.pop(name)
            self.plot.removeItem(curve)
            self.plot.removeItem(scatter)

            if self.legend is not None:
                for i, (_, lbl) in enumerate(list(self.legend.items)):
                    if getattr(lbl, "signal_name", None) == name:
                        sample, label = self.legend.items.pop(i)
                        self.legend.layout.removeItem(sample)
                        self.legend.layout.removeItem(label)
                        sample.hide()
                        label.hide()
                        break

        if self._needs_autorange:
            self.plot.enableAutoRange()
            return

        vb.disableAutoRange()
        vb.setXRange(x_range[0], x_range[1], padding=0)
        vb.setYRange(y_range[0], y_range[1], padding=0)

    def highlight(self, selected: str | None):
        for name, (curve, scatter) in self._items.items():
            opacity = 1.0 if name == selected else 0.35
            curve.setOpacity(opacity)
            scatter.setOpacity(opacity)

    def _on_legend_double_click(self, name: str):
        self._on_select(name)
        self._on_edit(name)
