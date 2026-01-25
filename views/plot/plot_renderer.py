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

    def clear(self):
        self.plot.clear()
        self._items.clear()
        self.legend = None

    def render(self, plot_data):
        self.clear()
        self.legend = self.plot.addLegend(offset=(10, 10))

        pen_style = {
            "Solid": Qt.SolidLine,
            "Dashed": Qt.DashLine,
            "Dotted": Qt.DotLine,
        }

        for data in plot_data:
            pen = pg.mkPen(
                color=data["style"]["color"],
                width=data["style"]["width"],
                style=pen_style.get(data["style"]["style"], Qt.SolidLine),
            )

            curve = pg.PlotDataItem(
                data["x"],
                data["y"],
                pen=pen,
            )
            curve.setCurveClickable(False)
            curve.setAcceptHoverEvents(False)

            sx, sy = downsample(data["x"], data["y"])

            scatter = SelectableScatter(
                label=data["label"],
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
                text=data["label"],
                signal_name=data["label"],
                on_double_click=self._on_legend_double_click,
            )

            row = len(self.legend.items)
            self.legend.items.append((sample, label))
            self.legend.layout.addItem(sample, row, 0)
            self.legend.layout.addItem(label, row, 1)

            self._items[data["label"]] = (curve, scatter)

        self.plot.enableAutoRange()

    def highlight(self, selected: str | None):
        for name, (curve, scatter) in self._items.items():
            opacity = 1.0 if name == selected else 0.35
            curve.setOpacity(opacity)
            scatter.setOpacity(opacity)

    def _on_legend_double_click(self, name: str):
        self._on_select(name)
        self._on_edit(name)
