from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from views.widgets.ribbon_button import RibbonButton, RibbonGroup, RibbonTabButton


@dataclass
class PlotRibbonActions:
    # Signals tab
    add_signal: QAction
    add_derived: QAction
    save_config: QAction
    load_config: QAction
    append_config: QAction
    export_image: QAction
    export_csv: QAction
    # View tab
    rescale: QAction
    rescale_x: QAction
    rescale_y: QAction
    auto_scroll: QAction
    grid_toggle: QAction
    legend_toggle: QAction
    y_axis_separate: QAction
    open_graph_settings: Callable[[], None]
    # Cursor tab
    cursor: QAction
    copy_snapshot: QAction
    dual_cursor: QAction
    follow_latest: QAction
    snap_cursor: QAction
    display_delta: QAction
    display_avg: QAction
    display_min_max: QAction
    display_count: QAction
    # Tools tab
    playback: QAction
    view_fft: QAction
    open_time_settings: Callable[[], None]


class PlotRibbonBar(QWidget):
    """Ribbon bar for plot windows (Signals / View / Cursor / Tools tabs)."""

    _TAB_H: int = 24
    _CONTENT_H: int = 80

    def __init__(
        self,
        actions: PlotRibbonActions,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RibbonBar")

        self._all_buttons: list[RibbonButton] = []
        self._collapsed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Tab row ──────────────────────────────────────────────────────────
        tab_row = QWidget()
        tab_row.setFixedHeight(self._TAB_H)
        tab_layout = QHBoxLayout(tab_row)
        tab_layout.setContentsMargins(4, 0, 4, 0)
        tab_layout.setSpacing(0)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tab_buttons: list[RibbonTabButton] = []

        for idx, label in enumerate(["Signals", "View", "Cursor", "Tools"]):
            btn = RibbonTabButton(label)
            self._tab_group.addButton(btn, idx)
            self._tab_buttons.append(btn)
            tab_layout.addWidget(btn)

        tab_layout.addStretch()

        self._collapse_btn = QToolButton()
        self._collapse_btn.setObjectName("ribbon_collapse_btn")
        self._collapse_btn.setFixedSize(24, 24)
        self._collapse_btn.setAutoRaise(True)
        self._collapse_btn.setToolTip(get_text("plot_ribbon_collapse_tooltip"))
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        tab_layout.addWidget(self._collapse_btn)

        outer.addWidget(tab_row)

        # ── Content stack ─────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setFixedHeight(self._CONTENT_H)
        outer.addWidget(self._stack)

        self._stack.addWidget(self._build_signals_page(actions))
        self._stack.addWidget(self._build_view_page(actions))
        self._stack.addWidget(self._build_cursor_page(actions))
        self._stack.addWidget(self._build_tools_page(actions))

        self._tab_group.idClicked.connect(self._activate_tab)
        self._activate_tab(0)

        self._update_collapse_icon()
        self.setFixedHeight(self._TAB_H + self._CONTENT_H)

        _f10 = QShortcut(QKeySequence(Qt.Key.Key_F10), self)
        _f10.setContext(Qt.ShortcutContext.WindowShortcut)
        _f10.activated.connect(self._toggle_collapse)

        # Reload icons when the palette changes (theme switch from main window)
        app = QGuiApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self.reload_icons)

    # ── collapse ──────────────────────────────────────────────────────────────

    def _update_collapse_icon(self) -> None:
        from views.icons import icon as _icon
        icon_name = "chevron-up" if not self._collapsed else "chevron-down"
        self._collapse_btn.setIcon(_icon(icon_name, size=16))
        self._collapse_btn.setIconSize(QSize(16, 16))
        tip = "Collapse ribbon  (F10)" if not self._collapsed else "Anchor ribbon  (F10)"
        self._collapse_btn.setToolTip(tip)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._stack.setVisible(not self._collapsed)
        self._update_collapse_icon()
        self.setFixedHeight(self._TAB_H if self._collapsed else self._TAB_H + self._CONTENT_H)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self._collapsed:
            self._stack.setVisible(True)
            self.setFixedHeight(self._TAB_H + self._CONTENT_H)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._collapsed and self._stack.isVisible():
            self._stack.setVisible(False)
            self.setFixedHeight(self._TAB_H)

    # ── private helpers ───────────────────────────────────────────────────────

    def _make_sep(self) -> QWidget:
        sep = QWidget()
        sep.setObjectName("ribbon_sep")
        sep.setFixedWidth(1)
        sep.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        return sep

    def _check_grp(self, title: str, items: list[tuple[str, QAction]], max_rows: int = 3) -> QWidget:
        """Compact ribbon group with checkboxes in columns of at most max_rows each."""
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(8, 6, 8, 0)
        outer_layout.setSpacing(0)

        content = QWidget()
        cols_layout = QHBoxLayout(content)
        cols_layout.setContentsMargins(0, 0, 0, 0)
        cols_layout.setSpacing(8)

        col_layout: QVBoxLayout | None = None
        for i, (text, action) in enumerate(items):
            if i % max_rows == 0:
                col_w = QWidget()
                col_layout = QVBoxLayout(col_w)
                col_layout.setContentsMargins(0, 0, 0, 0)
                col_layout.setSpacing(4)
                cols_layout.addWidget(col_w)

            ck = QCheckBox(text)
            ck.setObjectName("ribbon_check")
            ck.setChecked(action.isChecked())
            ck.setEnabled(action.isEnabled())
            ck.toggled.connect(action.setChecked)
            action.toggled.connect(
                lambda v, c=ck: (c.blockSignals(True), c.setChecked(v), c.blockSignals(False))
            )
            action.changed.connect(lambda a=action, c=ck: c.setEnabled(a.isEnabled()))
            col_layout.addWidget(ck)

        outer_layout.addWidget(content, 1)

        lbl = QLabel(title)
        lbl.setObjectName("ribbon_group_title")
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer_layout.addWidget(lbl)

        return outer

    def _page(self, groups: list[QWidget]) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)
        for i, grp in enumerate(groups):
            layout.addWidget(grp)
            if i < len(groups) - 1:
                layout.addWidget(self._make_sep())
        layout.addStretch()
        return page

    def _btn(self, icon_name: str, label: str) -> RibbonButton:
        b = RibbonButton(icon_name, label)
        self._all_buttons.append(b)
        return b

    def _btn_from_action(
        self,
        icon_name: str,
        label: str,
        action: QAction,
    ) -> RibbonButton:
        """Create a button wired to a QAction (non-checkable)."""
        btn = self._btn(icon_name, label)
        btn.setEnabled(action.isEnabled())
        btn.clicked.connect(action.trigger)
        action.changed.connect(lambda: btn.setEnabled(action.isEnabled()))
        return btn

    def _toggle_btn_from_action(
        self,
        icon_name: str,
        label: str,
        action: QAction,
    ) -> RibbonButton:
        """Create a checkable toggle button wired to a checkable QAction."""
        btn = self._btn(icon_name, label)
        btn.setCheckable(True)
        btn.setChecked(action.isChecked())
        btn.setEnabled(action.isEnabled())
        # button → action
        btn.clicked.connect(action.trigger)
        # action → button (programmatic state changes)
        action.toggled.connect(lambda v: (btn.blockSignals(True), btn.setChecked(v), btn.blockSignals(False)))
        action.changed.connect(lambda: btn.setEnabled(action.isEnabled()))
        return btn

    def _activate_tab(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._tab_buttons):
            active = i == index
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _build_signals_page(self, a: PlotRibbonActions) -> QWidget:
        add_grp = RibbonGroup("Add")
        add_grp.add_button(self._btn_from_action("plus", "Signal", a.add_signal))
        add_grp.add_button(self._btn_from_action("square-function", "Derived", a.add_derived))

        cfg_grp = RibbonGroup("Preset")
        cfg_grp.add_button(self._btn_from_action("save", "Save", a.save_config))
        cfg_grp.add_button(self._btn_from_action("folder-open", "Open", a.load_config))
        cfg_grp.add_button(self._btn_from_action("folder-plus", "Append", a.append_config))

        export_grp = RibbonGroup("Export")
        export_grp.add_button(self._btn_from_action("image", "Image", a.export_image))
        export_grp.add_button(self._btn_from_action("file-spreadsheet", "CSV", a.export_csv))

        return self._page([add_grp, cfg_grp, export_grp])

    def _build_view_page(self, a: PlotRibbonActions) -> QWidget:
        # "Zoom" — one-shot reset, visually separate from the persistent Auto Fit toggles
        zoom_grp = RibbonGroup("Zoom")
        zoom_btn = self._btn_from_action("maximize", "Rescale", a.rescale)
        zoom_btn.setToolTip(get_text("plot_ribbon_zoom_tooltip"))
        zoom_grp.add_button(zoom_btn)

        # "Auto Fit" — latching toggles: stay active until the user pans manually
        fit_grp = RibbonGroup("Auto Fit")
        fitx_btn = self._toggle_btn_from_action("arrow-left-right", "Fit X", a.rescale_x)
        fitx_btn.setToolTip(get_text("plot_ribbon_fit_x_tooltip"))
        fit_grp.add_button(fitx_btn)
        fity_btn = self._toggle_btn_from_action("arrow-up-down", "Fit Y", a.rescale_y)
        fity_btn.setToolTip(get_text("plot_ribbon_fit_y_tooltip"))
        fit_grp.add_button(fity_btn)

        nav_grp = RibbonGroup("Live")
        nav_grp.add_button(self._toggle_btn_from_action("play", "Live", a.auto_scroll))

        appear_grp = RibbonGroup("Appearance")
        appear_grp.add_button(self._toggle_btn_from_action("grid", "Grid", a.grid_toggle))
        appear_grp.add_button(self._toggle_btn_from_action("list", "Legend", a.legend_toggle))
        split_btn = self._toggle_btn_from_action("git-fork", "Split Y", a.y_axis_separate)
        split_btn.setToolTip(get_text("plot_ribbon_split_y_tooltip"))
        appear_grp.add_button(split_btn)
        graph_btn = self._btn("settings", "Graph")
        graph_btn.setToolTip(get_text("plot_ribbon_graph_settings_tooltip"))
        graph_btn.clicked.connect(a.open_graph_settings)
        self._all_buttons.append(graph_btn)
        appear_grp.add_button(graph_btn)

        return self._page([zoom_grp, fit_grp, nav_grp, appear_grp])

    def _build_cursor_page(self, a: PlotRibbonActions) -> QWidget:
        toggle_grp = RibbonGroup("Cursor")
        toggle_grp.add_button(self._toggle_btn_from_action("crosshair", "Cursor", a.cursor))

        options_grp = RibbonGroup("Options")
        dual_btn = self._toggle_btn_from_action("columns-2", "Dual", a.dual_cursor)
        dual_btn.setToolTip(get_text("plot_ribbon_dual_cursor_tooltip"))
        options_grp.add_button(dual_btn)

        follow_btn = self._toggle_btn_from_action("chevrons-right", "Follow", a.follow_latest)
        follow_btn.setToolTip(get_text("plot_ribbon_follow_tooltip"))
        options_grp.add_button(follow_btn)

        snap_btn = self._toggle_btn_from_action("magnet", "Snap", a.snap_cursor)
        snap_btn.setToolTip(get_text("plot_ribbon_snap_tooltip"))
        options_grp.add_button(snap_btn)

        show_grp = self._check_grp("Show", [
            ("Δ delta", a.display_delta),
            ("avg", a.display_avg),
            ("min / max", a.display_min_max),
            ("count", a.display_count),
        ], max_rows=2)

        actions_grp = RibbonGroup("Actions")
        btn_copy = self._btn("copy", "Copy")
        btn_copy.setEnabled(a.copy_snapshot.isEnabled())
        btn_copy.clicked.connect(a.copy_snapshot.trigger)
        a.copy_snapshot.changed.connect(lambda: btn_copy.setEnabled(a.copy_snapshot.isEnabled()))
        a.cursor.toggled.connect(lambda v: btn_copy.setEnabled(v))
        self._all_buttons.append(btn_copy)
        actions_grp.add_button(btn_copy)

        return self._page([toggle_grp, options_grp, show_grp, actions_grp])

    def _build_tools_page(self, a: PlotRibbonActions) -> QWidget:
        nav_grp = RibbonGroup("Navigate")
        nav_grp.add_button(self._toggle_btn_from_action("film", "Playback", a.playback))

        freq_grp = RibbonGroup("Frequency")
        fft_btn = self._btn_from_action("bar-chart-2", "FFT", a.view_fft)
        fft_btn.setToolTip(get_text("plot_ribbon_fft_tooltip"))
        freq_grp.add_button(fft_btn)

        time_grp = RibbonGroup("Time Config")
        btn_time = self._btn("clock", "Time Config")
        btn_time.setToolTip(get_text("plot_ribbon_time_config_tooltip"))
        btn_time.clicked.connect(a.open_time_settings)
        time_grp.add_button(btn_time)

        return self._page([nav_grp, freq_grp, time_grp])

    # ── public API ────────────────────────────────────────────────────────────

    def reload_icons(self) -> None:
        """Re-render all button icons with the current theme color."""
        for btn in self._all_buttons:
            btn.reload_icon()
        self._update_collapse_icon()
