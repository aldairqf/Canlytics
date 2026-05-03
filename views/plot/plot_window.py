from PySide6.QtWidgets import QMainWindow, QMenu, QFileDialog, QVBoxLayout, QWidget
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QCursor
import pyqtgraph as pg

from views.signal.signal_settings_dialog import GraphSettingsDialog
from views.settings.graph_settings_dialog import GraphSettingsDialog as PlotGraphSettingsDialog
from views.widgets.playback_bar import PlaybackBar
from .plot_items import ClickableViewBox
from .plot_renderer import PlotRenderer
from .plot_interaction import PlotInteraction
from .time_axis import TimeAxisItem
from .cursor_controller import CursorController
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.settings.time_config_dialog import TimeConfigDialog


class PlotWindow(QMainWindow):
    closed = Signal()

    def __init__(self, graph_vm, dbc_manager=None, timezone_mode="none"):
        super().__init__()
        self.vm = graph_vm
        self.dbc_manager = dbc_manager
        self.interaction = PlotInteraction()

        self.normalize_time = False
        self.timezone_mode = timezone_mode
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
        self._x_log_scale = False
        self._y_log_scale = False
        self._y_axis_mode = "shared"
        self._auto_rescale_on_changes = True
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
        self.renderer.set_axis_scales(x_log=self._x_log_scale, y_log=self._y_log_scale)
        self._apply_visual_config()

        if hasattr(self.view_box, "sigRangeChangedManually"):
            self.view_box.sigRangeChangedManually.connect(self._on_view_changed_manually)

        self.vm.data_changed.connect(self._redraw)

    def _on_normalize_time_toggled(self, checked: bool):
        self.normalize_time = checked
        fg = str(self._visual_config.get("axis_text_color", "#a7b0be"))
        if checked:
            self.time_axis.set_timezone("none")
            self.plot.setLabel("bottom", "Time (s)", color=fg)
        self.playback_bar.set_timezone(self._current_time_mode())
        self._apply_grid_config()
        self._redraw()

    def _on_view_changed_manually(self, *args):
        if hasattr(self, "renderer") and self.renderer:
            self.renderer.lock_autorange()

    def _setup_menu_bar(self):
        menu_plot = self.menuBar().addMenu("Settings")
        action_time = menu_plot.addAction("Time settings...")
        action_time.triggered.connect(self._open_time_settings)
        action_graph = menu_plot.addAction("Graph settings...")
        action_graph.triggered.connect(self._open_graph_settings)

        tools_menu = self.menuBar().addMenu("Tools")

        self._action_playback = tools_menu.addAction("Playback bar")
        self._action_playback.setCheckable(True)
        self._action_playback.setChecked(False)
        self._action_playback.toggled.connect(self._toggle_playback_bar)

        cursor_menu = tools_menu.addMenu("Cursor")

        self._action_cursor = cursor_menu.addAction("Enabled")
        self._action_cursor.setCheckable(True)
        self._action_cursor.setChecked(False)
        self._action_cursor.toggled.connect(self._toggle_cursor)

        self._action_follow_latest = cursor_menu.addAction("Follow latest data")
        self._action_follow_latest.setCheckable(True)
        self._action_follow_latest.setChecked(False)
        self._action_follow_latest.setEnabled(False)
        self._action_follow_latest.toggled.connect(self._toggle_follow_latest)

    def _open_time_settings(self):
        dlg = TimeConfigDialog(self._time_vm, parent=self)
        dlg.exec()

    def _open_graph_settings(self) -> None:
        dlg = PlotGraphSettingsDialog(
            y_axis_mode=self._y_axis_mode,
            x_log_scale=self._x_log_scale,
            y_log_scale=self._y_log_scale,
            auto_rescale_on_changes=self._auto_rescale_on_changes,
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
            self._x_log_scale = bool(cfg.get("x_log_scale", False))
            self._y_log_scale = bool(cfg.get("y_log_scale", False))
            self._auto_rescale_on_changes = bool(cfg.get("auto_rescale_on_changes", True))
            legend_cfg = cfg.get("legend", {})
            self._legend_visible = bool(legend_cfg.get("visible", True))
            self._legend_position = str(legend_cfg.get("position", "top_left"))
            self._legend_bg_opacity = float(legend_cfg.get("bg_opacity", 0.65))
            self._legend_border = bool(legend_cfg.get("border", True))
            self._visual_config = cfg.get("visual", self._visual_config)
            self.renderer.set_y_axis_mode(self._y_axis_mode)
            self.renderer.set_axis_scales(x_log=self._x_log_scale, y_log=self._y_log_scale)
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

    def _toggle_follow_latest(self, enabled: bool) -> None:
        self.cursor_controller.set_follow_latest(enabled)

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
        self.setWindowTitle("CAN Plot")
        self.resize(900, 600)

        self.view_box = ClickableViewBox(
            on_left_click=self._clear_selection,
            on_right_click=self._open_context_menu,
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

        self.playback_bar = PlaybackBar(self)
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

        self._setup_menu_bar()
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
        if not name or name not in self.vm.signals:
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

        edit_action = None
        remove_action = None
        duplicate_action = None

        if self.interaction.selected:
            edit_action = menu.addAction("Edit selected signal")
            remove_action = menu.addAction("Remove selected signal")
            duplicate_action = menu.addAction("Duplicate selected signal")
            menu.addSeparator()

        add_action = menu.addAction("Add signal")
        clear_action = menu.addAction("Remove all signals")
        menu.addSeparator()

        save_action = menu.addAction("Save config signals")
        load_action = menu.addAction("Load config signals")
        append_action = menu.addAction("Append config signals")
        menu.addSeparator()

        rescale_action = menu.addAction("Rescale view")

        action = menu.exec(QCursor.pos())

        if action == edit_action:
            self._edit_selected()
        elif action == remove_action:
            self._remove_selected()
        elif action == duplicate_action:
            self._duplicate_selected()
        elif action == add_action:
            self._add_signal()
        elif action == clear_action:
            self._reset()
        elif action == save_action:
            self._save_config()
        elif action == load_action:
            self._load_config()
        elif action == append_action:
            self._append_config()
        elif action == rescale_action:
            self.renderer.request_autorange()

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
        if self._auto_rescale_on_changes:
            self.renderer.request_autorange()
        self.vm.load_config(path)

    def _append_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Append signal configuration", "", "Signal config (*.conf)")
        if not path:
            return
        self.interaction.clear()
        if self._auto_rescale_on_changes:
            self.renderer.request_autorange()
        self.vm.append_config(path)

    def _add_signal(self):
        dlg = GraphSettingsDialog(self.vm, parent=self, dbc_manager=self.dbc_manager,
                                  default_color=self.vm.next_color())
        if dlg.exec():
            if self._auto_rescale_on_changes:
                self.renderer.request_autorange()
            self.vm.upsert_signal(dlg.get_signal())

    def _edit_selected(self):
        old_name = self.interaction.selected
        if not old_name or old_name not in self.vm.signals:
            return
        dlg = GraphSettingsDialog(self.vm, view_signal=self.vm.signals[old_name], parent=self, dbc_manager=self.dbc_manager)
        if dlg.exec():
            new_vs = dlg.get_signal()
            if self._auto_rescale_on_changes:
                self.renderer.request_autorange()
            new_name = self.vm.rename_signal(old_name, new_vs)
            self.interaction.select(new_name)

    def _remove_selected(self):
        name = self.interaction.selected
        if not name:
            return
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

    def _redraw(self):
        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        self.renderer.render(plot_data)
        self.renderer.highlight(self.interaction.selected)
        self._update_playback_range(plot_data)
        self.cursor_controller.on_redraw()

    def closeEvent(self, event):
        self.playback_bar.stop()
        self.closed.emit()
        super().closeEvent(event)
