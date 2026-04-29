import numpy as np
from PySide6.QtWidgets import QFrame, QLabel, QMainWindow, QMenu, QFileDialog, QVBoxLayout, QWidget
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QCursor
import pyqtgraph as pg

from views.settings.grid_config_dialog import GridConfigDialog
from views.signal.signal_settings_dialog import GraphSettingsDialog
from views.widgets.playback_bar import PlaybackBar
from .plot_items import ClickableViewBox
from .plot_renderer import PlotRenderer
from .plot_interaction import PlotInteraction
from .time_axis import TimeAxisItem
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
        self._cursor_enabled = False
        self._cursor_follow_latest = False
        self._cursor_time: float | None = None
        self._grid_config = {
            "enabled": False,
            "auto": True,
            "x_enabled": True,
            "y_enabled": True,
            "x_spacing": 1.0,
            "y_spacing": 1.0,
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

        if hasattr(self.view_box, "sigRangeChangedManually"):
            self.view_box.sigRangeChangedManually.connect(self._on_view_changed_manually)

        self.vm.data_changed.connect(self._redraw)

    def _on_normalize_time_toggled(self, checked: bool):
        self.normalize_time = checked
        if checked:
            self.time_axis.set_timezone("none")
            self.plot.setLabel("bottom", "Time (s)")
        self.playback_bar.set_timezone(self._current_time_mode())
        self._apply_grid_config()
        self._redraw()

    def _on_view_changed_manually(self, *args):
        if hasattr(self, "renderer") and self.renderer:
            self.renderer.lock_autorange()

    def _setup_menu_bar(self):
        menu_plot = self.menuBar().addMenu("Settings")
        action = menu_plot.addAction("Time settings...")
        action.triggered.connect(self._open_time_settings)

        tools_menu = self.menuBar().addMenu("Tools")

        self._action_playback = tools_menu.addAction("Playback bar")
        self._action_playback.setCheckable(True)
        self._action_playback.setChecked(False)
        self._action_playback.toggled.connect(self._toggle_playback_bar)

        self._action_crosshair = tools_menu.addAction("Crosshair")
        self._action_crosshair.setCheckable(True)
        self._action_crosshair.setChecked(False)
        self._action_crosshair.toggled.connect(self._toggle_crosshair)

        grid_action = tools_menu.addAction("Grid...")
        grid_action.triggered.connect(self._open_grid_settings)

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

    def _open_grid_settings(self) -> None:
        dlg = GridConfigDialog(self._grid_config, parent=self)
        if dlg.exec():
            self._grid_config = dlg.get_config()
            self._apply_grid_config()

    def _toggle_playback_bar(self, visible: bool) -> None:
        self.playback_bar.setVisible(visible)
        if not visible:
            self.playback_bar.stop()
            self.playback_bar.clear_values()
            self._cursor_line.setVisible(False)

    def _toggle_crosshair(self, enabled: bool) -> None:
        self._crosshair_enabled = enabled
        if not enabled:
            for item in (self._ch_v, self._ch_h):
                item.setVisible(False)
            self._crosshair_box.hide()
            if not self._cursor_enabled:
                self._value_box.hide()

    def _toggle_cursor(self, enabled: bool) -> None:
        self._cursor_enabled = enabled
        self._action_follow_latest.setEnabled(enabled)
        if not enabled:
            self._cursor_line.setVisible(False)
            self._cursor_time = None
            if not self._crosshair_enabled:
                self._value_box.hide()
            return

        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        self._move_cursor_to_latest(plot_data)

    def _toggle_follow_latest(self, enabled: bool) -> None:
        self._cursor_follow_latest = enabled
        if enabled and self._cursor_enabled:
            plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
            self._move_cursor_to_latest(plot_data)

    def _on_mouse_moved(self, pos_tuple) -> None:
        if not self._crosshair_enabled:
            return
        pos = pos_tuple[0]
        if not self.plot.sceneBoundingRect().contains(pos):
            for item in (self._ch_v, self._ch_h):
                item.setVisible(False)
            self._crosshair_box.hide()
            if not self._cursor_enabled:
                self._value_box.hide()
            return

        vb = self.plot.getViewBox()
        mouse_point = vb.mapSceneToView(pos)
        mx, my = mouse_point.x(), mouse_point.y()

        self._ch_v.setValue(mx)
        self._ch_h.setValue(my)

        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        best_value: float | None = None
        best_dist = float("inf")
        best_color = "#ffffff"
        best_label = ""
        for data in plot_data:
            xs = np.asarray(data["x"], dtype=float)
            ys = np.asarray(data["y"], dtype=float)
            if len(xs) < 2:
                continue
            v = float(np.interp(mx, xs, ys))
            dist = abs(v - my)
            if dist < best_dist:
                best_dist = dist
                best_value = v
                best_label = str(data["label"])
                c = data["style"]["color"]
                best_color = c.name() if hasattr(c, "name") else str(c)

        x_range, y_range = vb.viewRange()
        snap_threshold = (y_range[1] - y_range[0]) * 0.05
        if best_value is not None and best_dist < snap_threshold:
            self._ch_h.setValue(best_value)
            t_str = self._format_plot_time(mx)
            label_html = (
                f'<div style="color:#d8d8d8; font-weight:700;">{t_str}</div>'
                f'<div><span style="color:{best_color}; font-weight:600;">{best_label}:</span> '
                f'<span style="color:#f3f3f3;">{best_value:.6g}</span></div>'
            )
            self._show_crosshair_label(label_html, mx, best_value, x_range, y_range)
            for item in (self._ch_v, self._ch_h):
                item.setVisible(True)
            self._update_value_box(mx, plot_data)
        else:
            t_str = self._format_plot_time(mx)
            self._show_crosshair_label(
                f'<div style="color:#d8d8d8; font-weight:700;">{t_str}</div>',
                mx,
                my,
                x_range,
                y_range,
            )
            self._ch_v.setVisible(True)
            self._ch_h.setVisible(True)
            self._update_value_box(mx, plot_data)

    def _set_timezone(self, tz: str):
        self.timezone_mode = tz
        if tz not in ("none", None):
            self.normalize_time = False
        self.time_axis.set_timezone(tz)
        self.plot.setAxisItems({"bottom": self.time_axis})
        if tz in ("none", None):
            self.plot.setLabel("bottom", "Time (s)")
        else:
            self.plot.setLabel("bottom", f"Time ({tz})")
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
        self.plot.setLabel("bottom", "Time (s)" if self.timezone_mode in ("none", None) else f"Time ({self.timezone_mode})")
        self.plot.setLabel("left", "Value")
        self.plot.setMenuEnabled(False)
        self.plot.getViewBox().setMenuEnabled(False)
        self._apply_grid_config()

        # Cursor vertical
        self._cursor_line = pg.InfiniteLine(
            angle=90, movable=True,
            pen=pg.mkPen(color=(200, 200, 200, 160), width=1, style=Qt.DashLine),
        )
        self._cursor_line.setVisible(False)
        self.plot.addItem(self._cursor_line)
        self._cursor_line.sigPositionChanged.connect(self._on_cursor_line_changed)

        # Crosshair lines (hidden until enabled)
        self._ch_v = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(color=(180, 180, 255, 180), width=1),
        )
        self._ch_h = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen(color=(180, 180, 255, 180), width=1),
        )
        for item in (self._ch_v, self._ch_h):
            item.setVisible(False)
            self.plot.addItem(item, ignoreBounds=True)

        self._crosshair_enabled = False
        self._mouse_proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_mouse_moved,
        )

        self.playback_bar = PlaybackBar(self)
        self.playback_bar.set_timezone(self.timezone_mode)
        self.playback_bar.time_changed.connect(self._on_playback_time)
        self.playback_bar.setVisible(False)

        self._value_box = QFrame(self.plot)
        self._value_box.setObjectName("plotValueBox")
        self._value_box.setStyleSheet(
            "#plotValueBox {"
            "background-color: rgba(24, 24, 24, 215);"
            "border: 1px solid rgba(210, 210, 210, 80);"
            "border-radius: 6px;"
            "}"
        )
        self._value_box_label = QLabel(self._value_box)
        self._value_box_label.setTextFormat(Qt.RichText)
        self._value_box_label.setStyleSheet("color: #f0f0f0; padding: 6px;")
        self._value_box_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        value_box_layout = QVBoxLayout(self._value_box)
        value_box_layout.setContentsMargins(0, 0, 0, 0)
        value_box_layout.addWidget(self._value_box_label)
        self._value_box.hide()

        self._crosshair_box = QFrame(self.plot)
        self._crosshair_box.setObjectName("plotCrosshairBox")
        self._crosshair_box.setStyleSheet(
            "#plotCrosshairBox {"
            "background-color: rgba(24, 24, 24, 215);"
            "border: 1px solid rgba(210, 210, 210, 80);"
            "border-radius: 6px;"
            "}"
        )
        self._crosshair_box_label = QLabel(self._crosshair_box)
        self._crosshair_box_label.setTextFormat(Qt.RichText)
        self._crosshair_box_label.setStyleSheet("color: #f0f0f0; padding: 6px;")
        self._crosshair_box_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        crosshair_layout = QVBoxLayout(self._crosshair_box)
        crosshair_layout.setContentsMargins(0, 0, 0, 0)
        crosshair_layout.addWidget(self._crosshair_box_label)
        self._crosshair_box.hide()

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.playback_bar)
        self.setCentralWidget(container)

        self._setup_menu_bar()
        self._position_value_box()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_value_box()

    def _position_value_box(self) -> None:
        margin = 12
        width = 280
        self._value_box.resize(width, max(80, self._value_box.sizeHint().height()))
        self._value_box.move(self.plot.width() - width - margin, margin)

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

    def _current_time_mode(self) -> str:
        return "none" if self.normalize_time else (self.timezone_mode or "none")

    def _format_plot_time(self, t: float) -> str:
        return self.time_axis.format_value(t)

    def _show_crosshair_label(self, html: str, x: float, y: float, x_range: list[float], y_range: list[float]) -> None:
        self._crosshair_box_label.setText(html)
        self._crosshair_box.adjustSize()
        self._position_crosshair_label(x, y, x_range, y_range)
        self._crosshair_box.show()

    def _position_crosshair_label(self, x: float, y: float, x_range: list[float], y_range: list[float]) -> None:
        x_span = x_range[1] - x_range[0]
        y_span = y_range[1] - y_range[0]
        margin_x = x_span * 0.01 if x_span > 0 else 0.0
        margin_y = y_span * 0.02 if y_span > 0 else 0.0
        scene_pos = self.plot.getViewBox().mapViewToScene(QPointF(x, y))
        widget_pos = self.plot.mapFromScene(scene_pos)
        box_width = self._crosshair_box.width()
        box_height = self._crosshair_box.height()

        if x > x_range[0] + x_span * 0.72:
            pos_x = widget_pos.x() - box_width - 12
        else:
            pos_x = widget_pos.x() + 12

        if y > y_range[0] + y_span * 0.8:
            pos_y = widget_pos.y() - box_height - 12
        else:
            pos_y = widget_pos.y() + 12

        max_x = max(0, self.plot.width() - box_width - 4)
        max_y = max(0, self.plot.height() - box_height - 4)
        pos_x = max(4, min(max_x, pos_x))
        pos_y = max(4, min(max_y, pos_y))
        self._crosshair_box.move(int(pos_x), int(pos_y))

    def _on_cursor_line_changed(self) -> None:
        if not self._cursor_enabled:
            return
        self._cursor_time = float(self._cursor_line.value())
        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        self._update_value_box(self._cursor_time, plot_data)

    @staticmethod
    def _latest_x(plot_data: list) -> float | None:
        latest = None
        for data in plot_data:
            xs = data.get("x") or []
            if not xs:
                continue
            x_val = float(xs[-1])
            latest = x_val if latest is None else max(latest, x_val)
        return latest

    def _move_cursor_to_latest(self, plot_data: list) -> None:
        latest_x = self._latest_x(plot_data)
        if latest_x is None:
            self._cursor_line.setVisible(False)
            self._value_box.hide()
            return

        self._cursor_time = latest_x
        self._cursor_line.setValue(latest_x)
        self._cursor_line.setVisible(True)
        self._update_value_box(latest_x, plot_data)

    def _update_value_box(self, t: float, plot_data: list) -> None:
        if not plot_data:
            self._value_box.hide()
            return

        rows: list[str] = []
        for data in plot_data:
            xs = np.asarray(data["x"], dtype=float)
            ys = np.asarray(data["y"], dtype=float)
            if len(xs) < 2:
                continue
            value = float(np.interp(t, xs, ys))
            color = data["style"]["color"]
            color_name = color.name() if hasattr(color, "name") else str(color)
            rows.append(
                "<div style=\"margin-top:4px;\">"
                f'<span style="color:{color_name}; font-weight:600;">{data["label"]}:</span> '
                f'<span style="color:#f3f3f3;">{value:.6g}</span>'
                "</div>"
            )

        if not rows:
            self._value_box.hide()
            return

        ts = self._format_plot_time(t)
        html = (
            f'<div style="font-weight:700; color:#d8d8d8; margin-bottom:6px;">{ts}</div>'
            + "".join(rows)
        )
        self._value_box_label.setText(html)
        self._value_box.adjustSize()
        self._position_value_box()
        self._value_box.show()

    # ── playback ──────────────────────────────────────────────────────────────

    def _on_playback_time(self, t: float) -> None:
        self._cursor_line.setValue(t)
        self._cursor_line.setVisible(True)

        plot_data = self.vm.get_plot_data(normalize_time=self.normalize_time)
        if not plot_data:
            self._value_box.hide()
            return

        lines: list[str] = []
        colors: list[str] = []
        for data in plot_data:
            xs = np.asarray(data["x"], dtype=float)
            ys = np.asarray(data["y"], dtype=float)
            if len(xs) < 2:
                continue
            value = float(np.interp(t, xs, ys))
            lines.append(f"{value:.4g}")
            c = data["style"]["color"]
            colors.append(c.name() if hasattr(c, "name") else str(c))

        if not lines:
            self.playback_bar.clear_values()
            return

        html = "".join(
            f'<span style="color:{c};">{l}</span>&nbsp;&nbsp;'
            for l, c in zip(lines, colors)
        )
        self.playback_bar.set_values_html(html)
        if not self._crosshair_enabled:
            self._update_value_box(t, plot_data)

    def _update_playback_range(self, plot_data: list) -> None:
        all_x = [x for d in plot_data for x in d["x"]]
        if not all_x:
            return
        self.playback_bar.set_range(min(all_x), max(all_x))

    # ── existing methods ──────────────────────────────────────────────────────

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
        self.vm.load_config(path)

    def _append_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Append signal configuration", "", "Signal config (*.conf)")
        if not path:
            return
        self.interaction.clear()
        self.vm.append_config(path)

    def _add_signal(self):
        dlg = GraphSettingsDialog(self.vm, parent=self, dbc_manager=self.dbc_manager,
                                  default_color=self.vm.next_color())
        if dlg.exec():
            self.vm.upsert_signal(dlg.get_signal())

    def _edit_selected(self):
        old_name = self.interaction.selected
        if not old_name or old_name not in self.vm.signals:
            return
        dlg = GraphSettingsDialog(self.vm, view_signal=self.vm.signals[old_name], parent=self, dbc_manager=self.dbc_manager)
        if dlg.exec():
            new_vs = dlg.get_signal()
            new_name = new_vs.signal.name
            if new_name != old_name:
                self.vm.remove_signal(old_name)
            self.vm.upsert_signal(new_vs)
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
        if self._cursor_enabled:
            if self._cursor_follow_latest or self._cursor_time is None:
                self._move_cursor_to_latest(plot_data)
            else:
                self._cursor_line.setValue(self._cursor_time)
                self._cursor_line.setVisible(True)
                if not self._crosshair_enabled:
                    self._update_value_box(self._cursor_time, plot_data)

    def closeEvent(self, event):
        self.playback_bar.stop()
        self.closed.emit()
        super().closeEvent(event)
