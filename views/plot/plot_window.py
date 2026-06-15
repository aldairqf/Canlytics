from PySide6.QtWidgets import QMainWindow, QMenu, QFileDialog, QVBoxLayout, QWidget, QToolBar
from PySide6.QtCore import Signal as QtSignal, Qt, QSize
from PySide6.QtGui import QCursor, QAction
import pyqtgraph as pg

from config.app_config import get_text
from views.icons import icon
from views.signal.derived_signal_dialog import DerivedSignalDialog
from views.signal.signal_settings_dialog import SignalSettingsDialog
from views.settings.graph_settings_dialog import GraphSettingsDialog as PlotGraphSettingsDialog
from views.settings.cursor_settings_dialog import CursorSettingsDialog
from views.widgets.playback_bar import PlaybackBarWidget
from .plot_items import ClickableViewBox
from .plot_renderer import PlotRenderer
from .plot_interaction import PlotInteraction
from .time_axis import TimeAxisItem
from .cursor_controller import CursorController
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.settings.time_config_dialog import TimeConfigDialog


class PlotWindow(QMainWindow):
    closed = QtSignal()

    def __init__(self, graph_vm, dbc_manager=None, timezone_mode="none"):
        super().__init__()
        self.vm = graph_vm
        self.dbc_manager = dbc_manager
        self.interaction = PlotInteraction()

        self.normalize_time = False
        self.timezone_mode = timezone_mode
        self._auto_scroll = False
        self._grid_config = {
            "enabled": False,
            "auto": True,
            "x_enabled": True,
            "y_enabled": True,
            "x_spacing": 1.0,
            "y_spacing": 1.0,
        }
        self._legend_visible = True
        self._legend_position = "top_left"
        self._legend_bg_opacity = 0.65
        self._legend_border = True
        self._y_axis_mode = "shared"
        self._visual_config = {
            "background_color": "#000000",
            "axis_text_color": "#a7b0be",
        }

        self.time_axis = TimeAxisItem(timezone_mode=self.timezone_mode, orientation="bottom")

        self._time_vm = TimeConfigViewModel(
            normalize=self.normalize_time,
            timezone=self.timezone_mode,
            parent=self,
        )
        self._time_vm.normalize_changed.connect(self._on_normalize_time_toggled)
        self._time_vm.timezone_changed.connect(self._set_timezone)

        self._setup_ui()

        self.renderer = PlotRenderer(
            self.plot,
            on_select=self._on_select_signal,
            on_context=self._open_context_menu,
            on_edit=self._edit_selected_by_name,
        )
        self.renderer.set_legend_visible(self._legend_visible)
        self.renderer.set_legend_position(self._legend_position)
        self.renderer.set_legend_style(bg_opacity=self._legend_bg_opacity, border=self._legend_border)
        self.renderer.set_y_axis_mode(self._y_axis_mode)
        self._apply_visual_config()

        if hasattr(self.view_box, "sigRangeChangedManually"):
            self.view_box.sigRangeChangedManually.connect(self._on_view_changed_manually)

        self.vm.data_changed.connect(self._redraw)

    def _create_actions(self) -> None:
        self._action_add_signal = QAction(icon("plus"), "Signal", self)
        self._action_add_signal.setToolTip("Add signal to plot")
        self._action_add_signal.triggered.connect(self._add_signal)

        self._action_add_derived = QAction(icon("square-function"), "Derived", self)
        self._action_add_derived.setToolTip("Add derived (formula) signal")
        self._action_add_derived.triggered.connect(self._add_derived_signal)

        self._action_save_config = QAction(icon("save"), "Save", self)
        self._action_save_config.setToolTip("Save signal configuration to file")
        self._action_save_config.triggered.connect(self._save_config)

        self._action_load_config = QAction(icon("folder-open"), "Open", self)
        self._action_load_config.setToolTip("Load signal configuration from file")
        self._action_load_config.triggered.connect(self._load_config)

        self._action_append_config = QAction(icon("folder-plus"), "Append", self)
        self._action_append_config.setToolTip("Append signals from another config file")
        self._action_append_config.triggered.connect(self._append_config)

        self._action_rescale = QAction(icon("maximize"), "Rescale", self)
        self._action_rescale.setToolTip("Fit all data in view")
        self._action_rescale.triggered.connect(self._do_rescale)

        self._action_jump_to_latest = QAction(icon("chevrons-right"), "Latest", self)
        self._action_jump_to_latest.setToolTip("Jump viewport to latest data")
        self._action_jump_to_latest.triggered.connect(self._jump_to_latest)

        self._action_auto_scroll = QAction(icon("play"), "Live", self)
        self._action_auto_scroll.setCheckable(True)
        self._action_auto_scroll.setChecked(False)
        self._action_auto_scroll.setToolTip("Auto-scroll to follow incoming live data")
        self._action_auto_scroll.toggled.connect(self._set_auto_scroll)

        self._action_playback = QAction(icon("film"), "Playback", self)
        self._action_playback.setCheckable(True)
        self._action_playback.setChecked(False)
        self._action_playback.setToolTip("Show/hide playback bar")
        self._action_playback.toggled.connect(self._toggle_playback_bar)

        self._action_cursor = QAction(icon("crosshair"), "Cursor", self)
        self._action_cursor.setCheckable(True)
        self._action_cursor.setChecked(False)
        self._action_cursor.setToolTip("Show/hide cursor")
        self._action_cursor.toggled.connect(self._toggle_cursor)

        self._action_cursor_settings = QAction(icon("sliders-horizontal"), get_text("cursor_settings_menu"), self)
        self._action_cursor_settings.setToolTip(get_text("cursor_settings_title"))
        self._action_cursor_settings.triggered.connect(self._open_cursor_settings)

        self._action_follow_latest = QAction(get_text("cursor_follow_latest"), self)
        self._action_follow_latest.setCheckable(True)
        self._action_follow_latest.setChecked(False)
        self._action_follow_latest.setEnabled(False)
        self._action_follow_latest.toggled.connect(self._toggle_follow_latest)

        self._action_dual_cursor = QAction(get_text("cursor_dual"), self)
        self._action_dual_cursor.setCheckable(True)
        self._action_dual_cursor.setChecked(False)
        self._action_dual_cursor.setEnabled(False)
        self._action_dual_cursor.toggled.connect(self._toggle_dual_cursor)

        self._action_active_a = QAction(get_text("cursor_a"), self)
        self._action_active_a.setCheckable(True)
        self._action_active_a.setChecked(True)
        self._action_active_a.setEnabled(False)
        self._action_active_a.triggered.connect(lambda: self._set_active_cursor("A"))

        self._action_active_b = QAction(get_text("cursor_b"), self)
        self._action_active_b.setCheckable(True)
        self._action_active_b.setChecked(False)
        self._action_active_b.setEnabled(False)
        self._action_active_b.triggered.connect(lambda: self._set_active_cursor("B"))

        self._action_snap = QAction(get_text("cursor_snap_to_sample"), self)
        self._action_snap.setCheckable(True)
        self._action_snap.setChecked(True)
        self._action_snap.setEnabled(False)
        self._action_snap.toggled.connect(self._toggle_snap_to_sample)

        self._display_time = QAction(get_text("cursor_show_time"), self)
        self._display_time.setCheckable(True)
        self._display_time.setChecked(True)
        self._display_time.setEnabled(False)
        self._display_time.toggled.connect(lambda v: self.cursor_controller.set_display_options(show_time=v))

        self._display_values = QAction(get_text("cursor_show_values"), self)
        self._display_values.setCheckable(True)
        self._display_values.setChecked(True)
        self._display_values.setEnabled(False)
        self._display_values.toggled.connect(lambda v: self.cursor_controller.set_display_options(show_values=v))

        self._display_delta = QAction(get_text("cursor_show_delta"), self)
        self._display_delta.setCheckable(True)
        self._display_delta.setChecked(True)
        self._display_delta.setEnabled(False)
        self._display_delta.toggled.connect(lambda v: self.cursor_controller.set_display_options(show_delta=v))

        self._action_copy_snapshot = QAction(get_text("cursor_copy_snapshot"), self)
        self._action_copy_snapshot.setEnabled(False)
        self._action_copy_snapshot.triggered.connect(self._copy_cursor_snapshot)

        self._action_toggle_toolbar = QAction("Hide toolbar", self)
        self._action_toggle_toolbar.setShortcut("F10")
        self._action_toggle_toolbar.triggered.connect(self._toggle_toolbar)

    def _on_normalize_time_toggled(self, checked: bool):
        self.normalize_time = checked
        fg = str(self._visual_config.get("axis_text_color", "#a7b0be"))
        if checked:
            self.time_axis.set_timezone("none")
            self.plot.setLabel("bottom", "Time (s)", color=fg)
        self.playback_bar.set_timezone(self._current_time_mode())
        self._apply_grid_config()
        self._redraw()

    def _setup_toolbar(self) -> None:
        tb = QToolBar("Plot Tools", self)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(True)
        self._toolbar = tb
        self.addToolBar(tb)

        tb.addAction(self._action_add_signal)
        tb.addAction(self._action_add_derived)
        tb.addSeparator()
        tb.addAction(self._action_save_config)
        tb.addAction(self._action_load_config)
        tb.addAction(self._action_append_config)
        tb.addSeparator()
        tb.addAction(self._action_rescale)
        tb.addAction(self._action_jump_to_latest)
        tb.addAction(self._action_cursor)
        tb.addAction(self._action_auto_scroll)

    def _do_rescale(self) -> None:
        self.renderer.request_autorange()
        self._redraw()

    def _on_view_changed_manually(self, *args):
        if hasattr(self, "renderer") and self.renderer:
            self.renderer.lock_autorange()
        if hasattr(self, "_action_auto_scroll") and self._action_auto_scroll.isChecked():
            self._action_auto_scroll.setChecked(False)

    def _setup_menu_bar(self):
        view_menu = self.menuBar().addMenu("View")
        action_time = view_menu.addAction("Time settings...")
        action_time.triggered.connect(self._open_time_settings)
        action_graph = view_menu.addAction("Graph settings...")
        action_graph.triggered.connect(self._open_graph_settings)
        view_menu.addSeparator()
        view_menu.addAction(self._action_toggle_toolbar)

        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction(self._action_playback)
        tools_menu.addSeparator()
        tools_menu.addAction(self._action_cursor_settings)
        tools_menu.addAction(self._action_copy_snapshot)

        tools_menu.addSeparator()
        tools_menu.addAction(self._action_auto_scroll)
        tools_menu.addAction(self._action_jump_to_latest)

        data_menu = self.menuBar().addMenu("Data")
        data_menu.addAction(self._action_save_config)
        data_menu.addAction(self._action_load_config)
        data_menu.addAction(self._action_append_config)

    def _open_time_settings(self):
        dlg = TimeConfigDialog(self._time_vm, parent=self)
        dlg.exec()

    def _open_graph_settings(self) -> None:
        dlg = PlotGraphSettingsDialog(
            y_axis_mode=self._y_axis_mode,
            grid_config=self._grid_config,
            legend_config={
                "visible": self._legend_visible,
                "position": self._legend_position,
                "bg_opacity": self._legend_bg_opacity,
                "border": self._legend_border,
            },
            visual_config=self._visual_config,
            parent=self,
        )
        if dlg.exec():
            cfg = dlg.get_config()
            self._y_axis_mode = str(cfg.get("y_axis_mode", "shared"))
            legend_cfg = cfg.get("legend", {})
            self._legend_visible = bool(legend_cfg.get("visible", True))
            self._legend_position = str(legend_cfg.get("position", "top_left"))
            self._legend_bg_opacity = float(legend_cfg.get("bg_opacity", 0.65))
            self._legend_border = bool(legend_cfg.get("border", True))
            self._visual_config = cfg.get("visual", self._visual_config)
            self.renderer.set_y_axis_mode(self._y_axis_mode)
            self.renderer.set_legend_position(self._legend_position)
            self.renderer.set_legend_visible(self._legend_visible)
            self.renderer.set_legend_style(bg_opacity=self._legend_bg_opacity, border=self._legend_border)
            self._grid_config = cfg.get("grid", self._grid_config)
            self._apply_visual_config()
            self._apply_grid_config()
            self._redraw()

    def _toggle_playback_bar(self, visible: bool) -> None:
        self.playback_bar.setVisible(visible)
        if not visible:
            self.playback_bar.stop()
            self.playback_bar.clear_values()
            if not self.cursor_controller.enabled:
                self.cursor_controller.hide_cursor_line()

    def _toggle_cursor(self, enabled: bool) -> None:
        self.cursor_controller.set_enabled(enabled)
        self._action_follow_latest.setEnabled(enabled)
        self._action_dual_cursor.setEnabled(enabled)
        self._action_snap.setEnabled(enabled)
        self._display_time.setEnabled(enabled)
        self._display_values.setEnabled(enabled)
        self._display_delta.setEnabled(enabled)
        self._action_copy_snapshot.setEnabled(enabled)
        self._action_active_a.setEnabled(enabled)
        self._action_active_b.setEnabled(enabled and self._action_dual_cursor.isChecked())

    def _toggle_toolbar(self) -> None:
        visible = self._toolbar.isVisible()
        self._toolbar.setVisible(not visible)
        self._action_toggle_toolbar.setText("Show toolbar" if visible else "Hide toolbar")

    def _toggle_follow_latest(self, enabled: bool) -> None:
        self.cursor_controller.set_follow_latest(enabled)

    def _toggle_dual_cursor(self, enabled: bool) -> None:
        self.cursor_controller.set_dual_cursor(enabled)
        self._action_active_b.setEnabled(self._action_cursor.isChecked() and enabled)
        if not enabled:
            self._set_active_cursor("A")

    def _set_active_cursor(self, cursor_name: str) -> None:
        self.cursor_controller.set_active_cursor(cursor_name)
        is_a = cursor_name != "B"
        self._action_active_a.setChecked(is_a)
        self._action_active_b.setChecked(not is_a)

    def _toggle_snap_to_sample(self, enabled: bool) -> None:
        self.cursor_controller.set_snap_to_sample(enabled)

    def _copy_cursor_snapshot(self) -> None:
        self.cursor_controller.copy_snapshot_to_clipboard()

    def _open_cursor_settings(self) -> None:
        dlg = CursorSettingsDialog(self._cursor_settings_config(), parent=self)
        if dlg.exec():
            self._apply_cursor_settings(dlg.get_config())

    def _cursor_settings_config(self) -> dict[str, bool | str]:
        return {
            "enabled": self._action_cursor.isChecked(),
            "follow_latest": self._action_follow_latest.isChecked(),
            "snap_to_sample": self._action_snap.isChecked(),
            "dual_cursor": self._action_dual_cursor.isChecked(),
            "active_cursor": "B" if self._action_active_b.isChecked() else "A",
            "show_time": self._display_time.isChecked(),
            "show_values": self._display_values.isChecked(),
            "show_delta": self._display_delta.isChecked(),
        }

    def _apply_cursor_settings(self, config: dict[str, bool | str]) -> None:
        enabled = bool(config.get("enabled", False))
        dual_cursor = bool(config.get("dual_cursor", False))
        active_cursor = str(config.get("active_cursor", "A"))
        if active_cursor == "B" and not dual_cursor:
            active_cursor = "A"

        self._action_cursor.setChecked(enabled)
        self._action_follow_latest.setChecked(bool(config.get("follow_latest", False)))
        self._action_dual_cursor.setChecked(dual_cursor)
        self._action_snap.setChecked(bool(config.get("snap_to_sample", True)))
        self._display_time.setChecked(bool(config.get("show_time", True)))
        self._display_values.setChecked(bool(config.get("show_values", True)))
        self._display_delta.setChecked(bool(config.get("show_delta", True)))
        self._set_active_cursor(active_cursor)

    def _set_timezone(self, tz: str):
        self.timezone_mode = tz
        fg = str(self._visual_config.get("axis_text_color", "#a7b0be"))
        if tz not in ("none", None):
            self.normalize_time = False
        self.time_axis.set_timezone(tz)
        self.plot.setAxisItems({"bottom": self.time_axis})
        if tz in ("none", None):
            self.plot.setLabel("bottom", "Time (s)", color=fg)
        else:
            self.plot.setLabel("bottom", f"Time ({tz})", color=fg)
        self.plot.repaint()
        self.playback_bar.set_timezone(self._current_time_mode())
        self._apply_grid_config()
        self._redraw()

    def _setup_ui(self):
        self.setWindowTitle("Canlytics — Plot")
        self.resize(900, 600)

        self.view_box = ClickableViewBox(
            on_left_click=self._clear_selection,
            on_right_click=self._open_context_menu,
            on_double_click=self._do_rescale,
        )

        self.plot = pg.PlotWidget(
            viewBox=self.view_box,
            axisItems={"bottom": self.time_axis},
        )
        fg = str(self._visual_config.get("axis_text_color", "#a7b0be"))
        self.plot.setLabel(
            "bottom",
            "Time (s)" if self.timezone_mode in ("none", None) else f"Time ({self.timezone_mode})",
            color=fg,
        )
        self.plot.setLabel("left", "Value", color=fg)
        self.plot.setMenuEnabled(False)
        self.plot.getViewBox().setMenuEnabled(False)
        self._apply_visual_config()
        self._apply_grid_config()

        self.cursor_controller = CursorController(
            self.plot,
            get_plot_data=lambda: self.vm.get_plot_data(normalize_time=self.normalize_time),
            format_time=self._format_plot_time,
        )

        self.playback_bar = PlaybackBarWidget(self)
        self.playback_bar.set_timezone(self.timezone_mode)
        self.playback_bar.time_changed.connect(self._on_playback_time)
        self.playback_bar.setVisible(False)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.playback_bar)
        self.setCentralWidget(container)

        self._create_actions()
        self._setup_menu_bar()
        self._setup_toolbar()
        self.cursor_controller.position_value_box()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.cursor_controller.position_value_box()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            direction = -1 if event.key() == Qt.Key_Left else 1
            plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
            moved = self.cursor_controller.nudge_to_next_sample(direction, plot_data=plot_data)
            if moved and self.cursor_controller.has_time():
                self.playback_bar.set_values_html(
                    self.cursor_controller.playback_values_html(
                        float(self.cursor_controller.cursor_time), plot_data
                    )
                )
                event.accept()
                return
        super().keyPressEvent(event)

    def _apply_grid_config(self) -> None:
        enabled = bool(self._grid_config.get("enabled", False))
        auto = bool(self._grid_config.get("auto", True))
        x_enabled = enabled and bool(self._grid_config.get("x_enabled", True))
        y_enabled = enabled and bool(self._grid_config.get("y_enabled", True))

        self.plot.showGrid(x=x_enabled, y=y_enabled, alpha=0.25 if enabled else 0.0)

        x_axis = self.plot.getAxis("bottom")
        y_axis = self.plot.getAxis("left")

        if auto or not enabled:
            x_axis.setTickSpacing()
            y_axis.setTickSpacing()
            return

        x_spacing = float(self._grid_config.get("x_spacing", 1.0))
        y_spacing = float(self._grid_config.get("y_spacing", 1.0))

        if x_enabled:
            x_axis.setTickSpacing(major=x_spacing, minor=x_spacing / 2.0)
        else:
            x_axis.setTickSpacing()

        if y_enabled:
            y_axis.setTickSpacing(major=y_spacing, minor=y_spacing / 2.0)
        else:
            y_axis.setTickSpacing()

    def _apply_visual_config(self) -> None:
        bg = str(self._visual_config.get("background_color", "#000000"))
        fg = str(self._visual_config.get("axis_text_color", "#a7b0be"))
        self.plot.setBackground(bg)
        for name in ("left", "bottom", "right", "top"):
            axis = self.plot.getAxis(name)
            if axis is not None:
                axis.setPen(pg.mkPen(fg))
                axis.setTextPen(pg.mkPen(fg))
        self.plot.setLabel("left", "Value", color=fg)
        bottom_label = "Time (s)" if self.timezone_mode in ("none", None) else f"Time ({self.timezone_mode})"
        self.plot.setLabel("bottom", bottom_label, color=fg)

    def _current_time_mode(self) -> str:
        return "none" if self.normalize_time else (self.timezone_mode or "none")

    def _format_plot_time(self, t: float) -> str:
        return self.time_axis.format_value(t)

    # Playback
    def _on_playback_time(self, t: float) -> None:
        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        self.cursor_controller.set_time(t, plot_data=plot_data, force_visible=True)

        if not plot_data:
            self.playback_bar.clear_values()
            return

        html = self.cursor_controller.playback_values_html(t, plot_data)
        self.playback_bar.set_values_html(html)

    def _update_playback_range(self, plot_data: list) -> None:
        all_x = [x for d in plot_data for x in d["x"]]
        if not all_x:
            return
        self.playback_bar.set_range(min(all_x), max(all_x))

    # Existing methods
    def _edit_selected_by_name(self, name: str):
        if not name or (name not in self.vm.signals and name not in self.vm.derived):
            return
        self.interaction.select(name)
        self.renderer.highlight(name)
        self._edit_selected()

    def _on_select_signal(self, name: str):
        self.interaction.select(name)
        self.renderer.highlight(name)

    def _clear_selection(self):
        self.interaction.clear()
        self.renderer.highlight(None)

    def _open_context_menu(self):
        menu = QMenu(self)

        edit_action = remove_action = duplicate_action = None
        if self.interaction.selected:
            edit_action = menu.addAction("Edit selected signal")
            remove_action = menu.addAction("Remove selected signal")
            duplicate_action = menu.addAction("Duplicate selected signal")
            menu.addSeparator()

        menu.addAction(self._action_add_signal)
        menu.addAction(self._action_add_derived)
        clear_action = menu.addAction("Remove all signals")
        menu.addSeparator()
        menu.addAction(self._action_save_config)
        menu.addAction(self._action_load_config)
        menu.addAction(self._action_append_config)
        menu.addSeparator()
        menu.addAction(self._action_rescale)

        action = menu.exec(QCursor.pos())

        if action == edit_action:
            self._edit_selected()
        elif action == remove_action:
            self._remove_selected()
        elif action == duplicate_action:
            self._duplicate_selected()
        elif action == clear_action:
            self._reset()

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save signal configuration", "", "Signal config (*.conf)")
        if not path:
            return
        self.vm.save_config(path)

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load signal configuration", "", "Signal config (*.conf)")
        if not path:
            return
        self.interaction.clear()
        self.renderer.request_autorange()
        self.vm.load_config(path)

    def _append_config(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Append signal configuration",
            "",
            "Signal config (*.conf)",
        )
        if not paths:
            return
        self.interaction.clear()
        self.renderer.request_autorange()
        for path in paths:
            self.vm.append_config(path)

    def _add_signal(self):
        dlg = SignalSettingsDialog(self.vm, parent=self, dbc_manager=self.dbc_manager,
                                   default_color=self.vm.next_color())
        if dlg.exec():
            self.renderer.request_autorange()
            self.vm.upsert_signal(dlg.get_signal())

    def _add_derived_signal(self):
        dlg = DerivedSignalDialog(self.vm, parent=self, default_color=self.vm.next_color())
        if dlg.exec():
            self.renderer.request_autorange()
            self.vm.upsert_derived(dlg.get_derived_view_signal())

    def _edit_selected(self):
        old_name = self.interaction.selected
        if not old_name:
            return
        if old_name in self.vm.derived:
            dvs = self.vm.derived[old_name]
            dlg = DerivedSignalDialog(self.vm, dvs=dvs, parent=self)
            if dlg.exec():
                new_dvs = dlg.get_derived_view_signal()
                self.renderer.request_autorange()
                new_name = self.vm.rename_derived(old_name, new_dvs)
                self.interaction.select(new_name)
            return
        if old_name not in self.vm.signals:
            return
        dlg = SignalSettingsDialog(self.vm, view_signal=self.vm.signals[old_name], parent=self, dbc_manager=self.dbc_manager)
        if dlg.exec():
            new_vs = dlg.get_signal()
            self.renderer.request_autorange()
            new_name = self.vm.rename_signal(old_name, new_vs)
            self.interaction.select(new_name)

    def _remove_selected(self):
        name = self.interaction.selected
        if not name:
            return
        if name in self.vm.derived:
            self.vm.remove_derived(name)
        else:
            self.vm.remove_signal(name)
        self.interaction.clear()

    def _reset(self):
        self.interaction.clear()
        self.vm.clear()

    def _duplicate_selected(self):
        name = self.interaction.selected
        if not name:
            return
        new_name = self.vm.duplicate_signal(name)
        if new_name:
            self.interaction.select(new_name)

    def _set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = bool(enabled)
        if enabled:
            self._jump_to_latest()

    def _jump_to_latest(self) -> None:
        self._auto_scroll = True
        if hasattr(self, "_action_auto_scroll"):
            self._action_auto_scroll.blockSignals(True)
            self._action_auto_scroll.setChecked(True)
            self._action_auto_scroll.blockSignals(False)
        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        if not plot_data:
            return
        self._apply_auto_scroll(plot_data, force=True)

    def _apply_auto_scroll(self, plot_data: list, *, force: bool = False) -> None:
        x_latest = None
        for d in plot_data:
            xs = d.get("x") or []
            if len(xs) > 0:
                v = float(xs[-1])
                if x_latest is None or v > x_latest:
                    x_latest = v
        if x_latest is None:
            return
        vb = self.plot.getViewBox()
        x0, x1 = vb.viewRange()[0]
        if not force and x_latest <= x1:
            return
        width = max(x1 - x0, 1.0)
        self.renderer.lock_autorange()
        vb.setXRange(x_latest - width, x_latest, padding=0)

    def _redraw(self):
        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        if self._auto_scroll and plot_data and not self.renderer._needs_autorange:
            self._apply_auto_scroll(plot_data)
        self.renderer.render(plot_data)
        self.renderer.highlight(self.interaction.selected)
        self._update_playback_range(plot_data)
        self.cursor_controller.on_redraw()

    def closeEvent(self, event):
        self.playback_bar.stop()
        self.closed.emit()
        super().closeEvent(event)
