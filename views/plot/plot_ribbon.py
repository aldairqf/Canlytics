from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication
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
    # View tab
    rescale: QAction
    jump_to_latest: QAction
    auto_scroll: QAction
    playback: QAction
    open_time_settings: Callable[[], None]
    open_graph_settings: Callable[[], None]
    # Cursor tab
    cursor: QAction
    cursor_settings: QAction
    copy_snapshot: QAction


class PlotRibbonBar(QWidget):
    """Ribbon bar for plot windows (Signals / View / Cursor tabs)."""

    def __init__(
        self,
        actions: PlotRibbonActions,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RibbonBar")

        self._all_buttons: list[RibbonButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Tab row ──────────────────────────────────────────────────────────
        tab_row = QWidget()
        tab_row.setFixedHeight(24)
        tab_layout = QHBoxLayout(tab_row)
        tab_layout.setContentsMargins(4, 0, 8, 0)
        tab_layout.setSpacing(0)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tab_buttons: list[RibbonTabButton] = []

        for idx, label in enumerate(["Signals", "View", "Cursor"]):
            btn = RibbonTabButton(label)
            self._tab_group.addButton(btn, idx)
            self._tab_buttons.append(btn)
            tab_layout.addWidget(btn)

        tab_layout.addStretch()
        outer.addWidget(tab_row)

        # ── Content stack ─────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setFixedHeight(80)
        outer.addWidget(self._stack)

        self._stack.addWidget(self._build_signals_page(actions))
        self._stack.addWidget(self._build_view_page(actions))
        self._stack.addWidget(self._build_cursor_page(actions))

        self._tab_group.idClicked.connect(self._activate_tab)
        self._activate_tab(0)

        # Reload icons when the palette changes (theme switch from main window)
        app = QGuiApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self.reload_icons)

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

        return self._page([add_grp, cfg_grp])

    def _build_view_page(self, a: PlotRibbonActions) -> QWidget:
        nav_grp = RibbonGroup("Navigate")
        nav_grp.add_button(self._btn_from_action("maximize", "Rescale", a.rescale))
        nav_grp.add_button(self._btn_from_action("chevrons-right", "Latest", a.jump_to_latest))
        nav_grp.add_button(self._toggle_btn_from_action("play", "Live", a.auto_scroll))
        nav_grp.add_button(self._toggle_btn_from_action("film", "Playback", a.playback))

        sett_grp = RibbonGroup("Settings")
        btn_time = self._btn("clock", "Time")
        btn_time.clicked.connect(a.open_time_settings)
        sett_grp.add_button(btn_time)

        btn_graph = self._btn("settings", "Graph")
        btn_graph.clicked.connect(a.open_graph_settings)
        sett_grp.add_button(btn_graph)

        return self._page([nav_grp, sett_grp])

    def _build_cursor_page(self, a: PlotRibbonActions) -> QWidget:
        grp = RibbonGroup("Cursor")
        grp.add_button(self._toggle_btn_from_action("crosshair", "Cursor", a.cursor))
        grp.add_button(self._btn_from_action("sliders-horizontal", "Settings", a.cursor_settings))

        btn_copy = self._btn("copy", "Copy")
        btn_copy.setEnabled(a.copy_snapshot.isEnabled())
        btn_copy.clicked.connect(a.copy_snapshot.trigger)
        a.copy_snapshot.changed.connect(lambda: btn_copy.setEnabled(a.copy_snapshot.isEnabled()))
        # Also sync enabled state when cursor is toggled
        a.cursor.toggled.connect(lambda v: btn_copy.setEnabled(v))
        self._all_buttons.append(btn_copy)
        grp.add_button(btn_copy)

        return self._page([grp])

    # ── public API ────────────────────────────────────────────────────────────

    def reload_icons(self) -> None:
        """Re-render all button icons with the current theme color."""
        for btn in self._all_buttons:
            btn.reload_icon()
