from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from config.theme import available_themes
from views.widgets.ribbon_button import RibbonButton, RibbonGroup, RibbonTabButton


@dataclass
class RibbonCallbacks:
    on_load: Callable[[], None]
    on_append: Callable[[], None]
    on_save: Callable[[], None]
    on_clear: Callable[[], None]
    on_open_dbc: Callable[[], None]
    on_open_plot: Callable[[], None]
    on_analyze_data: Callable[[], None]
    on_candidate_interpretations: Callable[[], None]
    on_signal_coverage: Callable[[], None]
    on_real_time_analysis: Callable[[], None]
    on_time_config: Callable[[], None]
    on_time_filter: Callable[[], None]
    on_connection: Callable[[], None]
    on_set_theme: Callable[[str], None]
    on_about: Callable[[], None]
    current_theme: str = "Dark"


class RibbonBar(QWidget):
    """Excel/SolidWorks-style ribbon bar for the main window.

    Placed via QMainWindow.setMenuWidget() so it fills the menu-bar slot
    without requiring any extra container widget.
    """

    _TAB_H: int = 24
    _CONTENT_H: int = 80

    def __init__(
        self,
        callbacks: RibbonCallbacks,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RibbonBar")

        self._all_buttons: list[RibbonButton] = []
        self._theme_actions: dict[str, QAction] = {}
        self._recent_logs_menu: QMenu | None = None
        self._collapsed = False
        self._btn_realtime: RibbonButton | None = None

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

        for idx, key in enumerate(
            ["ribbon_tab_home", "ribbon_tab_analysis", "ribbon_tab_settings"]
        ):
            btn = RibbonTabButton(get_text(key))
            self._tab_group.addButton(btn, idx)
            self._tab_buttons.append(btn)
            tab_layout.addWidget(btn)

        tab_layout.addStretch()

        self._collapse_btn = QToolButton()
        self._collapse_btn.setObjectName("ribbon_collapse_btn")
        self._collapse_btn.setFixedSize(24, 24)
        self._collapse_btn.setAutoRaise(True)
        self._collapse_btn.setToolTip(get_text("ribbon_collapse_tooltip"))
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        tab_layout.addWidget(self._collapse_btn)

        outer.addWidget(tab_row)

        # ── Content stack ─────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setFixedHeight(self._CONTENT_H)
        outer.addWidget(self._stack)

        self._stack.addWidget(self._build_home_page(callbacks))
        self._stack.addWidget(self._build_analysis_page(callbacks))
        self._stack.addWidget(self._build_settings_page(callbacks))

        self._tab_group.idClicked.connect(self._activate_tab)
        self._activate_tab(0)

        self._update_collapse_icon()
        self.setFixedHeight(self._TAB_H + self._CONTENT_H)

        _f10 = QShortcut(QKeySequence(Qt.Key.Key_F10), self)
        _f10.setContext(Qt.ShortcutContext.WindowShortcut)
        _f10.activated.connect(self._toggle_collapse)

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
        # When anchoring, always show the stack; when collapsing, hide it.
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

    def _activate_tab(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._tab_buttons):
            active = i == index
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _build_home_page(self, cb: RibbonCallbacks) -> QWidget:
        # File group — Load Log is a split button exposing Recent Logs
        file_grp = RibbonGroup(get_text("ribbon_group_file"))

        btn_load = self._btn("folder-open", get_text("ribbon_btn_load_log"))
        btn_load.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._recent_logs_menu = QMenu(btn_load)
        btn_load.setMenu(self._recent_logs_menu)
        btn_load.clicked.connect(cb.on_load)
        file_grp.add_button(btn_load)

        btn_append = self._btn("folder-plus", get_text("ribbon_btn_append"))
        btn_append.clicked.connect(cb.on_append)
        file_grp.add_button(btn_append)

        btn_save = self._btn("save", get_text("ribbon_btn_save"))
        btn_save.clicked.connect(cb.on_save)
        file_grp.add_button(btn_save)

        btn_clear = self._btn("trash-2", get_text("ribbon_btn_clear"))
        btn_clear.clicked.connect(cb.on_clear)
        file_grp.add_button(btn_clear)

        # DBC group
        dbc_grp = RibbonGroup(get_text("ribbon_group_dbc"))
        btn_dbc = self._btn("database", get_text("ribbon_btn_dbc_manager"))
        btn_dbc.clicked.connect(cb.on_open_dbc)
        dbc_grp.add_button(btn_dbc)

        # Stream group
        stream_grp = RibbonGroup(get_text("ribbon_group_stream"))
        btn_conn = self._btn("wifi", get_text("ribbon_btn_connection"))
        btn_conn.clicked.connect(cb.on_connection)
        stream_grp.add_button(btn_conn)

        return self._page([file_grp, dbc_grp, stream_grp])

    def _build_analysis_page(self, cb: RibbonCallbacks) -> QWidget:
        grp = RibbonGroup(get_text("ribbon_group_analysis"))

        btn_plot = self._btn("chart-line", get_text("ribbon_btn_add_plot"))
        btn_plot.clicked.connect(cb.on_open_plot)
        grp.add_button(btn_plot)

        btn_analyze = self._btn("gauge", get_text("ribbon_btn_analyze"))
        btn_analyze.clicked.connect(cb.on_analyze_data)
        grp.add_button(btn_analyze)

        btn_cand = self._btn("search", get_text("ribbon_btn_candidates"))
        btn_cand.clicked.connect(cb.on_candidate_interpretations)
        grp.add_button(btn_cand)

        btn_coverage = self._btn("list-checks", get_text("ribbon_btn_signal_coverage"))
        btn_coverage.setToolTip(get_text("menu_signal_coverage"))
        btn_coverage.clicked.connect(cb.on_signal_coverage)
        grp.add_button(btn_coverage)

        self._btn_realtime = self._btn("radio", get_text("ribbon_btn_real_time", "Real Time"))
        self._btn_realtime.setEnabled(False)
        self._btn_realtime.setToolTip(get_text("ribbon_realtime_tooltip"))
        self._btn_realtime.clicked.connect(cb.on_real_time_analysis)
        grp.add_button(self._btn_realtime)

        return self._page([grp])

    def _build_settings_page(self, cb: RibbonCallbacks) -> QWidget:
        # Time group
        time_grp = RibbonGroup(get_text("ribbon_group_time"))

        btn_tc = self._btn("clock", get_text("ribbon_btn_time_config"))
        btn_tc.clicked.connect(cb.on_time_config)
        time_grp.add_button(btn_tc)

        btn_tf = self._btn("sliders-horizontal", get_text("ribbon_btn_time_filter"))
        btn_tf.clicked.connect(cb.on_time_filter)
        time_grp.add_button(btn_tf)

        # Display group — Theme is an instant-popup split button
        disp_grp = RibbonGroup(get_text("ribbon_group_display"))

        btn_theme = self._btn("palette", get_text("ribbon_btn_theme"))
        btn_theme.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        theme_menu = QMenu(btn_theme)
        theme_ag = QActionGroup(btn_theme)
        theme_ag.setExclusive(True)
        for name in available_themes():
            act = QAction(name, btn_theme, checkable=True)
            act.setChecked(name == cb.current_theme)
            act.triggered.connect(lambda _checked=False, n=name: cb.on_set_theme(n))
            theme_ag.addAction(act)
            theme_menu.addAction(act)
            self._theme_actions[name] = act
        btn_theme.setMenu(theme_menu)
        disp_grp.add_button(btn_theme)

        # Help group
        help_grp = RibbonGroup(get_text("ribbon_group_help", "Help"))
        btn_about = self._btn("circle-help", get_text("ribbon_btn_about", "About"))
        btn_about.clicked.connect(cb.on_about)
        help_grp.add_button(btn_about)

        return self._page([time_grp, disp_grp, help_grp])

    # ── public API ────────────────────────────────────────────────────────────

    def get_recent_logs_menu(self) -> QMenu | None:
        """Return the QMenu used as the recent-logs dropdown on the Load Log button."""
        return self._recent_logs_menu

    def set_real_time_analysis_enabled(self, enabled: bool) -> None:
        if self._btn_realtime is not None:
            self._btn_realtime.setEnabled(enabled)

    def reload_icons(self) -> None:
        """Re-render all button icons with the current theme color (call after theme switch)."""
        for btn in self._all_buttons:
            btn.reload_icon()
        self._update_collapse_icon()

    def update_theme_check(self, name: str) -> None:
        """Sync the checked state of the Theme dropdown after an external theme change."""
        for n, act in self._theme_actions.items():
            act.setChecked(n == name)
