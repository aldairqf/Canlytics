from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QMainWindow, QToolBar

from config.theme import active_plot_defaults
from views.icons import icon as _icon


class FFTWindow(QMainWindow):
    """Frequency-domain view: amplitude spectrum of one or more signals.

    X axis = Frequency (Hz).  Y axis = amplitude (same units as source signal)
    or dB (20·log10 of amplitude).  Multiple signals are overlaid as separate
    curves with their own colours.

    Call ``set_data(entries, range_label)`` to populate.  The window is
    reused: calling set_data again replaces the previous content.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FFT — Frequency Analysis")
        self.resize(720, 420)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._entries: list[dict] = []
        self._db_mode = False

        defaults = active_plot_defaults()
        bg = defaults["background_color"]
        fg = defaults["axis_text_color"]

        self.plot = pg.PlotWidget(background=bg)
        self.plot.setLabel("bottom", "Frequency", units="Hz", color=fg)
        self.plot.setLabel("left", "Amplitude", color=fg)
        self.plot.getAxis("bottom").setPen(pg.mkPen(color=fg))
        self.plot.getAxis("left").setPen(pg.mkPen(color=fg))
        self.plot.getAxis("bottom").setTextPen(pg.mkPen(color=fg))
        self.plot.getAxis("left").setTextPen(pg.mkPen(color=fg))
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.setCentralWidget(self.plot)

        tb = QToolBar()
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        self._action_db = QAction(_icon("bar-chart-2", size=16), "dB scale", self)
        self._action_db.setCheckable(True)
        self._action_db.setToolTip("Switch between linear amplitude and dB (20·log10)")
        self._action_db.toggled.connect(self._on_db_toggled)
        tb.addAction(self._action_db)

        app = QGuiApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._apply_theme)

    # ── public API ────────────────────────────────────────────────────────────

    def set_data(
        self,
        entries: list[dict],
        range_label: str = "",
    ) -> None:
        """Populate the FFT plot.

        entries: list of dicts with keys:
            label (str), color (QColor), freqs (ndarray Hz), mags (ndarray)
        range_label: shown in the window title, e.g. "A–B (3.2 s)"
        """
        self._entries = entries
        title = "FFT — Frequency Analysis"
        if range_label:
            title = f"FFT — {range_label}"
        self.setWindowTitle(title)
        self._redraw()

    # ── private ───────────────────────────────────────────────────────────────

    def _on_db_toggled(self, db: bool) -> None:
        self._db_mode = db
        defaults = active_plot_defaults()
        fg = defaults["axis_text_color"]
        if db:
            self.plot.setLabel("left", "Amplitude (dB)", color=fg)
        else:
            self.plot.setLabel("left", "Amplitude", color=fg)
        self._redraw()

    def _redraw(self) -> None:
        self.plot.clear()
        legend = self.plot.addLegend(offset=(10, 10))

        for entry in self._entries:
            freqs: np.ndarray = entry["freqs"]
            mags: np.ndarray = entry["mags"]
            color = entry["color"]
            label: str = entry["label"]

            if self._db_mode:
                with np.errstate(divide="ignore", invalid="ignore"):
                    y = 20.0 * np.log10(np.maximum(mags, 1e-12))
            else:
                y = mags

            color_name = color.name() if hasattr(color, "name") else str(color)
            self.plot.plot(
                freqs,
                y,
                pen=pg.mkPen(color=color_name, width=1.5),
                name=label,
            )

    def _apply_theme(self) -> None:
        defaults = active_plot_defaults()
        bg = defaults["background_color"]
        fg = defaults["axis_text_color"]
        self.plot.setBackground(bg)
        self.plot.getAxis("bottom").setPen(pg.mkPen(color=fg))
        self.plot.getAxis("left").setPen(pg.mkPen(color=fg))
        self.plot.getAxis("bottom").setTextPen(pg.mkPen(color=fg))
        self.plot.getAxis("left").setTextPen(pg.mkPen(color=fg))
        self.plot.setLabel("bottom", "Frequency", units="Hz", color=fg)
        label = "Amplitude (dB)" if self._db_mode else "Amplitude"
        self.plot.setLabel("left", label, color=fg)
        self._redraw()
