from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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
    playback: QAction
    # Cursor tab
    cursor: QAction
    copy_snapshot: QAction
    dual_cursor: QAction
    follow_latest: QAction
    snap_cursor: QAction
    # Settings tab
    open_time_settings: Callable[[], None]
    open_graph_settings: Callable[[], None]


class PlotRibbonBar(QWidget):
    """Ribbon bar for plot windows (Signals / View / Cursor / Settings tabs)."""

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

        for idx, label in enumerate(["Signals", "View", "Cursor", "Settings"]):
            btn = RibbonTabButton(label)
            self._tab_group.addButton(btn, idx)
            self._tab_buttons.append(btn)
            tab_layout.addWidget(btn)

        tab_layout.addStretch()

        self._collapse_btn = QToolButton()
        self._collapse_btn.setObjectName("ribbon_collapse_btn")
        self._collapse_btn.setFixedSize(24, 24)
        self._collapse_btn.setAutoRaise(True)
        self._collapse_btn.setToolTip("Collapse ribbon  (F10)")
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
        self._stack.addWidget(self._build_settings_page(actions))

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

    def _page(self, groups: list[RibbonGroup]) -> QWidget:
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

        cfg_grp = RibbonGroup("Config")
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
        zoom_btn.setToolTip("Reset zoom to fit all data (one-shot)")
        zoom_grp.add_button(zoom_btn)

        # "Auto Fit" — latching toggles: stay active until the user pans manually
        fit_grp = RibbonGroup("Auto Fit")
        fitx_btn = self._toggle_btn_from_action("arrow-left-right", "Fit X", a.rescale_x)
        fitx_btn.setToolTip("Keep X axis fitted to data (disables on manual pan)")
        fit_grp.add_button(fitx_btn)
        fity_btn = self._toggle_btn_from_action("arrow-up-down", "Fit Y", a.rescale_y)
        fity_btn.setToolTip("Keep Y axis fitted to data (disables on manual pan)")
        fit_grp.add_button(fity_btn)

        nav_grp = RibbonGroup("Navigate")
        nav_grp.add_button(self._toggle_btn_from_action("play", "Live", a.auto_scroll))
        nav_grp.add_button(self._toggle_btn_from_action("film", "Playback", a.playback))

        return self._page([zoom_grp, fit_grp, nav_grp])

    def _build_cursor_page(self, a: PlotRibbonActions) -> QWidget:
        toggle_grp = RibbonGroup("Cursor")
        toggle_grp.add_button(self._toggle_btn_from_action("crosshair", "Cursor", a.cursor))

        options_grp = RibbonGroup("Options")
        dual_btn = self._toggle_btn_from_action("columns-2", "Dual", a.dual_cursor)
        dual_btn.setToolTip("Show a second cursor (B) for measuring intervals")
        options_grp.add_button(dual_btn)

        follow_btn = self._toggle_btn_from_action("chevrons-right", "Follow", a.follow_latest)
        follow_btn.setToolTip("Cursor follows the latest data point")
        options_grp.add_button(follow_btn)

        snap_btn = self._toggle_btn_from_action("magnet", "Snap", a.snap_cursor)
        snap_btn.setToolTip("Snap cursor to nearest sample point")
        options_grp.add_button(snap_btn)

        actions_grp = RibbonGroup("Actions")
        btn_copy = self._btn("copy", "Copy")
        btn_copy.setEnabled(a.copy_snapshot.isEnabled())
        btn_copy.clicked.connect(a.copy_snapshot.trigger)
        a.copy_snapshot.changed.connect(lambda: btn_copy.setEnabled(a.copy_snapshot.isEnabled()))
        a.cursor.toggled.connect(lambda v: btn_copy.setEnabled(v))
        self._all_buttons.append(btn_copy)
        actions_grp.add_button(btn_copy)

        return self._page([toggle_grp, options_grp, actions_grp])

    def _build_settings_page(self, a: PlotRibbonActions) -> QWidget:
        time_grp = RibbonGroup("Time")
        btn_time = self._btn("clock", "Time")
        btn_time.setToolTip("Configure time display and timezone")
        btn_time.clicked.connect(a.open_time_settings)
        time_grp.add_button(btn_time)

        display_grp = RibbonGroup("Display")
        btn_graph = self._btn("settings", "Graph")
        btn_graph.setToolTip("Configure plot appearance, grid, and legend")
        btn_graph.clicked.connect(a.open_graph_settings)
        display_grp.add_button(btn_graph)

        return self._page([time_grp, display_grp])

    # ── public API ────────────────────────────────────────────────────────────

    def reload_icons(self) -> None:
        """Re-render all button icons with the current theme color."""
        for btn in self._all_buttons:
            btn.reload_icon()
        self._update_collapse_icon()
