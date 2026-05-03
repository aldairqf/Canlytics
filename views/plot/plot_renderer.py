from PySide6.QtCore import Qt
import pyqtgraph as pg
import numpy as np

from .plot_items import SelectableScatter, downsample


class PlotRenderer:
    def __init__(self, plot_widget: pg.PlotWidget, on_select, on_context, on_edit):
        self.plot = plot_widget
        self._items: dict[str, tuple[pg.PlotDataItem, SelectableScatter, str]] = {}
        self._containers: dict[str, pg.ViewBox] = {}
        self._axis_items: dict[str, pg.AxisItem] = {}
        self._axis_order: list[str] = []
        self._on_select = on_select
        self._on_context = on_context
        self._on_edit = on_edit
        self.legend = None
        self._legend_visible = True
        self._needs_autorange = True
        self._y_axis_mode = "shared"
        self._x_log_scale = False
        self._y_log_scale = False
        self._legend_offset = (10, 10)
        self._legend_position = "top_left"
        self._legend_bg_opacity = 0.65
        self._legend_border = True
        self._base_layout_shift = 0
        self._visibility_state: dict[str, bool] = {}

        vb = self.plot.getViewBox()
        vb.sigResized.connect(self._sync_aux_geometry)
        self._marker_symbol_map = {
            "Circle": "o",
            "Square": "s",
            "Triangle": "t",
            "Diamond": "d",
            "Cross": "x",
            "Plus": "+",
        }

    def request_autorange(self):
        self._needs_autorange = True
        vb = self.plot.getViewBox()
        vb.enableAutoRange(x=True, y=True)
        for box in self._containers.values():
            try:
                box.enableAutoRange(x=True, y=True)
            except Exception:
                pass

    def lock_autorange(self):
        self._needs_autorange = False
        self.plot.getViewBox().disableAutoRange()
        for box in self._containers.values():
            if box is not self.plot.getViewBox():
                box.disableAutoRange()

    def clear(self):
        self._clear_aux_axes()
        self.plot.clear()
        self._items.clear()
        self._containers.clear()
        self._destroy_legend()
        self._needs_autorange = True

    def set_legend_visible(self, visible: bool) -> None:
        self._legend_visible = visible
        self._ensure_legend()
        if self.legend is not None:
            self.legend.setVisible(visible)

    def set_y_axis_mode(self, mode: str) -> None:
        mode = "separate" if mode == "separate" else "shared"
        if mode == self._y_axis_mode:
            return
        self._reset_for_mode_switch()
        self._y_axis_mode = mode
        self._apply_axis_mode_ui()

    def set_y_log_scale(self, enabled: bool) -> None:
        self.set_axis_scales(x_log=self._x_log_scale, y_log=bool(enabled))

    def set_axis_scales(self, *, x_log: bool, y_log: bool) -> None:
        self._x_log_scale = bool(x_log)
        x_log_effective = self._x_log_scale and self._can_enable_log_x()
        self._y_log_scale = bool(y_log)
        self.plot.setLogMode(x=x_log_effective, y=self._y_log_scale)
        for axis in self._axis_items.values():
            axis.setLogMode(x_log_effective, self._y_log_scale)
        for curve, _, _ in self._items.values():
            curve.setLogMode(x_log_effective, self._y_log_scale)

    def set_step_mode(self, enabled: bool) -> None:
        # Backward-compatible no-op: step mode is now per signal.
        _ = enabled

    def set_legend_position(self, position: str) -> None:
        mapping = {
            "top_left": (10, 10),
            "top_right": (-10, 10),
            "bottom_left": (10, -10),
            "bottom_right": (-10, -10),
        }
        self._legend_position = position if position in mapping else "top_left"
        self._legend_offset = mapping[self._legend_position]
        if self.legend is not None:
            try:
                self.legend.anchor((0, 0), (0, 0), offset=self._legend_offset)
            except Exception:
                pass
            self._apply_legend_style()

    def set_legend_style(self, *, bg_opacity: float, border: bool) -> None:
        self._legend_bg_opacity = max(0.0, min(1.0, float(bg_opacity)))
        self._legend_border = bool(border)
        self._apply_legend_style()

    def render(self, plot_data):
        vb = self.plot.getViewBox()
        self._ensure_legend()

        pen_style = {
            "Solid": Qt.SolidLine,
            "Dashed": Qt.DashLine,
            "Dotted": Qt.DotLine,
        }

        x_range, y_range = vb.viewRange()
        aux_y_ranges = {
            sid: box.viewRange()[1]
            for sid, box in self._containers.items()
            if box is not vb
        }

        alive = set()
        data_by_id = {str(d.get("id") or d["label"]): d for d in plot_data}

        for data in plot_data:
            sid = str(data.get("id") or data["label"])
            label = str(data["label"])
            alive.add(sid)

            pen = pg.mkPen(
                color=data["style"]["color"],
                width=data["style"]["width"],
                style=pen_style.get(data["style"]["style"], Qt.SolidLine),
            )

            if sid in self._items:
                curve, scatter, _ = self._items[sid]
                curve.setPen(pen)
                curve.setLogMode(self._x_log_scale, self._y_log_scale)
                curve.setData(
                    data["x"],
                    data["y"],
                    stepMode=("left" if bool(data["style"].get("step_mode", False)) else None),
                )
                scatter._label = label

                sx, sy = downsample(data["x"], data["y"])
                scatter.setData(x=sx, y=sy)
                self._apply_marker_style(scatter, data["style"])
                if sid in self._axis_items:
                    self._axis_items[sid].setLabel(label)
                self._items[sid] = (curve, scatter, label)
                visible = self._visibility_state.get(sid, curve.isVisible())
                self._set_signal_visible(sid, visible, refresh_legend=False)
                self._style_axis_for_signal(sid, selected=False)
            else:
                curve = pg.PlotDataItem(data["x"], data["y"], pen=pen)
                curve.setCurveClickable(False)
                curve.setAcceptHoverEvents(False)
                curve.setLogMode(self._x_log_scale, self._y_log_scale)
                curve.setData(
                    data["x"],
                    data["y"],
                    stepMode=("left" if bool(data["style"].get("step_mode", False)) else None),
                )

                sx, sy = downsample(data["x"], data["y"])
                scatter = SelectableScatter(
                    label=label,
                    on_select=self._on_select,
                    on_context=self._on_context,
                    x=sx,
                    y=sy,
                    size=10,
                    pen=None,
                    brush=(0, 0, 0, 0),
                    hoverable=True,
                )
                self._apply_marker_style(scatter, data["style"])

                target_box = self._get_target_box(sid, label)
                target_box.addItem(curve)
                target_box.addItem(scatter)

                self._items[sid] = (curve, scatter, label)
                self._visibility_state.setdefault(sid, True)
                self._set_signal_visible(sid, self._visibility_state[sid], refresh_legend=False)
                self._style_axis_for_signal(sid, selected=False)

        for sid in list(self._items.keys()):
            if sid in alive:
                continue

            self._remove_signal(sid)

        # Safety net: if anything drifted out of sync (e.g. after consecutive
        # renames), rebuild items from the authoritative plot_data labels.
        if set(self._items.keys()) != alive:
            self._force_rebuild_from_data(data_by_id, pen_style)
            alive = set(self._items.keys())

        self._rebuild_legend()
        self._sync_aux_geometry()

        if self._needs_autorange:
            if self._y_axis_mode == "separate":
                x_min = min((min(d["x"]) for d in plot_data if d.get("x")), default=None)
                x_max = max((max(d["x"]) for d in plot_data if d.get("x")), default=None)
                vb.disableAutoRange(axis=vb.YAxis)
                if x_min is not None and x_max is not None and x_max > x_min:
                    vb.setXRange(x_min, x_max, padding=0.02)
                for box in self._containers.values():
                    if box is not vb:
                        box.enableAutoRange(axis=box.YAxis)
                        box.setXLink(vb)
                        try:
                            box.autoRange(padding=0.02)
                        except Exception:
                            pass
            else:
                self.plot.enableAutoRange()
            return

        vb.disableAutoRange()
        vb.setXRange(x_range[0], x_range[1], padding=0)
        if self._y_axis_mode == "shared":
            vb.setYRange(y_range[0], y_range[1], padding=0)

        for sid, box in self._containers.items():
            if box is vb:
                continue
            box.disableAutoRange()
            box.setXRange(x_range[0], x_range[1], padding=0)
            yr = aux_y_ranges.get(sid)
            if yr is not None:
                box.setYRange(yr[0], yr[1], padding=0)

    def highlight(self, selected: str | None):
        selected_sid = None
        for sid, (_, _, label) in self._items.items():
            if label == selected:
                selected_sid = sid
                break

        for sid, (curve, scatter, label) in self._items.items():
            opacity = 1.0 if label == selected else 0.35
            curve.setOpacity(opacity)
            scatter.setOpacity(opacity)
            self._style_axis_for_signal(sid, selected=(sid == selected_sid))
            box = self._containers.get(sid)
            if box is not None and box is not self.plot.getViewBox():
                box.setZValue(10 if sid == selected_sid else 5)

    def _on_legend_double_click(self, name: str):
        self._on_select(name)
        self._on_edit(name)

    def _get_target_box(self, sid: str, label: str) -> pg.ViewBox:
        if self._y_axis_mode != "separate":
            self._containers[sid] = self.plot.getViewBox()
            return self.plot.getViewBox()

        box = self._containers.get(sid)
        if box is None or box is self.plot.getViewBox():
            box = self._create_aux_viewbox(sid, label)
            self._containers[sid] = box
        return box

    def _create_aux_viewbox(self, sid: str, label: str) -> pg.ViewBox:
        main_vb = self.plot.getViewBox()
        axis = pg.AxisItem("left")
        axis.setLabel(label)
        axis.setLogMode(False, self._y_log_scale)

        aux_vb = pg.ViewBox()
        aux_vb.setXLink(main_vb)
        aux_vb.setMouseEnabled(x=False, y=True)
        aux_vb.setMenuEnabled(False)
        aux_vb.setZValue(5)
        self.plot.scene().addItem(aux_vb)
        axis.linkToView(aux_vb)

        self._axis_items[sid] = axis
        self._axis_order.append(sid)
        self._reflow_custom_axes()
        self._sync_aux_geometry()
        return aux_vb

    def _sync_aux_geometry(self):
        main_vb = self.plot.getViewBox()
        for box in self._containers.values():
            if box is main_vb:
                continue
            box.setGeometry(main_vb.sceneBoundingRect())
            box.linkedViewChanged(main_vb, box.XAxis)

    def _remove_signal(self, sid: str) -> None:
        curve, scatter, _ = self._items.pop(sid)
        container = self._containers.pop(sid, self.plot.getViewBox())
        container.removeItem(curve)
        container.removeItem(scatter)

        if sid in self._axis_items:
            axis = self._axis_items.pop(sid)
            if sid in self._axis_order:
                self._axis_order.remove(sid)
            self._layout_remove_if_present(axis)
            axis.setParentItem(None)
            if container is not self.plot.getViewBox():
                self.plot.scene().removeItem(container)
            self._reflow_custom_axes()
        self._visibility_state.pop(sid, None)

    def _clear_aux_axes(self) -> None:
        for _, axis in list(self._axis_items.items()):
            self._layout_remove_if_present(axis)
            axis.setParentItem(None)
        self._axis_items.clear()
        self._axis_order.clear()

        main_vb = self.plot.getViewBox()
        removed: set[int] = set()
        for box in self._containers.values():
            if box is main_vb:
                continue
            if id(box) in removed:
                continue
            removed.add(id(box))
            self.plot.scene().removeItem(box)

    def _reflow_custom_axes(self) -> None:
        # In separate mode, place custom axes at the left by shifting base
        # PlotItem layout to the right by N columns.
        shift = len(self._axis_order) if self._y_axis_mode == "separate" else 0
        self._shift_base_layout(shift)

        for axis in self._axis_items.values():
            self._layout_remove_if_present(axis)

        base_col = 0
        for i, sid in enumerate(self._axis_order):
            axis = self._axis_items.get(sid)
            if axis is None:
                continue
            self.plot.plotItem.layout.addItem(axis, 2, base_col + i)

    def _rebuild_plot_items(self) -> None:
        if not self._items:
            self._clear_aux_axes()
            self._containers.clear()
            return

        snapshot: list[tuple[str, pg.PlotDataItem, SelectableScatter, str]] = []
        for sid, (curve, scatter, label) in self._items.items():
            snapshot.append((sid, curve, scatter, label))

        self._clear_aux_axes()
        self._containers.clear()

        for sid, curve, scatter, label in snapshot:
            target_box = self._get_target_box(sid, label)
            target_box.addItem(curve)
            self.plot.getViewBox().addItem(scatter)

        self._sync_aux_geometry()
        self.set_y_log_scale(self._y_log_scale)
        self._apply_axis_mode_ui()

    def _reset_for_mode_switch(self) -> None:
        main_vb = self.plot.getViewBox()
        for sid, (curve, scatter, _) in list(self._items.items()):
            container = self._containers.get(sid, main_vb)
            try:
                container.removeItem(curve)
            except Exception:
                pass
            try:
                container.removeItem(scatter)
            except Exception:
                pass

        self._items.clear()
        self._clear_aux_axes()
        self._containers.clear()
        self._shift_base_layout(0)

    def _force_rebuild_from_data(self, data_by_id: dict[str, dict], pen_style: dict) -> None:
        for curve, scatter, _ in self._items.values():
            for box in set(self._containers.values()):
                try:
                    box.removeItem(curve)
                    box.removeItem(scatter)
                except Exception:
                    pass

        self._clear_aux_axes()
        self._items.clear()
        self._containers.clear()

        for sid, data in data_by_id.items():
            label = str(data["label"])
            pen = pg.mkPen(
                color=data["style"]["color"],
                width=data["style"]["width"],
                style=pen_style.get(data["style"]["style"], Qt.SolidLine),
            )

            curve = pg.PlotDataItem(data["x"], data["y"], pen=pen)
            curve.setCurveClickable(False)
            curve.setAcceptHoverEvents(False)
            curve.setLogMode(self._x_log_scale, self._y_log_scale)
            curve.setData(
                data["x"],
                data["y"],
                stepMode=("left" if bool(data["style"].get("step_mode", False)) else None),
            )

            sx, sy = downsample(data["x"], data["y"])
            scatter = SelectableScatter(
                label=label,
                on_select=self._on_select,
                on_context=self._on_context,
                x=sx,
                y=sy,
                size=10,
                pen=None,
                brush=(0, 0, 0, 0),
                hoverable=True,
            )
            self._apply_marker_style(scatter, data["style"])

            target_box = self._get_target_box(sid, label)
            target_box.addItem(curve)
            target_box.addItem(scatter)
            self._items[sid] = (curve, scatter, label)

    def _rebuild_legend(self) -> None:
        self._ensure_legend()
        if self.legend is None:
            return
        self.legend.setZValue(10_000)
        self.legend.setVisible(self._legend_visible)
        self.legend.clear()

        for _, (curve, _, label) in self._items.items():
            self.legend.addItem(curve, label)

        # Bind legend interactions in deterministic SID order.
        ordered_sids = list(self._items.keys())
        for idx, legend_item in enumerate(list(self.legend.items)):
            if idx >= len(ordered_sids):
                break
            sid = ordered_sids[idx]
            sample, label_item = legend_item
            _, _, signal_name = self._items[sid]

            def _on_dbl_click(ev, sig=signal_name):
                if ev.button() == Qt.LeftButton:
                    self._on_legend_double_click(sig)
                    ev.accept()
                else:
                    ev.ignore()

            try:
                label_item.mouseDoubleClickEvent = _on_dbl_click
            except Exception:
                pass

            def _on_sample_click(ev, target_sid=sid):
                if ev.button() != Qt.LeftButton:
                    ev.ignore()
                    return
                current = self._visibility_state.get(target_sid, True)
                self._set_signal_visible(target_sid, not current, refresh_legend=True)
                ev.accept()

            try:
                sample.mouseClickEvent = _on_sample_click
            except Exception:
                pass

    def _style_axis_for_signal(self, sid: str, selected: bool) -> None:
        axis = self._axis_items.get(sid)
        item = self._items.get(sid)
        if axis is None or item is None:
            return
        curve, _, label = item
        pen = curve.opts.get("pen")
        color = pen.color() if pen is not None else pg.mkColor("#b0b0b0")
        width = 2 if selected else 1
        axis_pen = pg.mkPen(color=color, width=width)
        axis.setPen(axis_pen)
        axis.setTextPen(axis_pen)
        axis.setLabel(label, color=color.name())

    def _apply_marker_style(self, scatter: SelectableScatter, style: dict) -> None:
        enabled = bool(style.get("marker_enabled", False))
        shape = str(style.get("marker_shape", "Circle"))
        symbol = self._marker_symbol_map.get(shape, "o")
        size = int(style.get("marker_size", 8))
        border_width = int(style.get("marker_border_width", 1))

        marker_color = style.get("marker_color", style.get("color"))
        marker_border_color = style.get("marker_border_color", style.get("color"))
        if not enabled:
            # Keep an invisible hit-area so signal selection still works even
            # when points are hidden.
            scatter.setPointsVisible(True)
            scatter.setSymbol("o")
            scatter.setBrush(pg.mkBrush(0, 0, 0, 0))
            scatter.setPen(pg.mkPen(0, 0, 0, 0))
            scatter.setSize(max(10, size))
            return

        scatter.setPointsVisible(True)
        brush = pg.mkBrush(marker_color)
        pen = pg.mkPen(marker_border_color, width=border_width) if border_width > 0 else None
        scatter.setSymbol(symbol)
        scatter.setBrush(brush)
        scatter.setPen(pen)
        scatter.setSize(max(2, size))

    def _destroy_legend(self) -> None:
        if self.legend is None:
            return
        try:
            if self.legend.scene() is not None:
                self.legend.scene().removeItem(self.legend)
        except Exception:
            pass
        self.legend = None

    def _apply_axis_mode_ui(self) -> None:
        is_separate = self._y_axis_mode == "separate"
        left_axis = self.plot.getAxis("left")
        self.plot.showAxis("left", not is_separate)
        self.plot.showAxis("right", False)
        self.plot.getViewBox().setMouseEnabled(x=True, y=not is_separate)
        if left_axis is not None:
            if is_separate:
                # Fully suppress the base Y axis in separate mode; only per-signal
                # axes should remain visible.
                left_axis.setVisible(False)
                left_axis.setStyle(showValues=False, tickLength=0)
                left_axis.setLabel("")
                try:
                    left_axis.setWidth(0)
                except Exception:
                    pass
            else:
                left_axis.setVisible(True)
                left_axis.setStyle(showValues=True, tickLength=-5)
                try:
                    left_axis.setWidth(None)
                except Exception:
                    pass

    def _set_signal_visible(self, sid: str, visible: bool, *, refresh_legend: bool = False) -> None:
        item = self._items.get(sid)
        if item is None:
            return
        curve, scatter, _ = item
        curve.setVisible(visible)
        scatter.setVisible(visible)
        axis = self._axis_items.get(sid)
        if axis is not None:
            axis.setVisible(visible)
        self._visibility_state[sid] = visible
        if refresh_legend:
            self._rebuild_legend()

    def _ensure_legend(self) -> None:
        if self.legend is None:
            self.legend = self.plot.addLegend(offset=self._legend_offset)
        if self.legend is not None:
            self.legend.setVisible(self._legend_visible)
            self.legend.setZValue(10_000)
            self._apply_legend_style()

    def _apply_legend_style(self) -> None:
        if self.legend is None:
            return
        alpha = int(255 * self._legend_bg_opacity)
        self.legend.setBrush(pg.mkBrush(18, 18, 18, alpha))
        if self._legend_border:
            self.legend.setPen(pg.mkPen(150, 150, 150, 180, width=1))
        else:
            self.legend.setPen(pg.mkPen(0, 0, 0, 0))

    def _can_enable_log_x(self) -> bool:
        # Guard against pyqtgraph AxisItem overflow warnings with huge X ranges
        # (common when X contains unix timestamps).
        x_values: list[np.ndarray] = []
        for curve, _, _ in self._items.values():
            x_data = curve.xData
            if x_data is None:
                continue
            arr = np.asarray(x_data, dtype=float)
            if arr.size == 0:
                continue
            x_values.append(arr)

        if not x_values:
            return False

        all_x = np.concatenate(x_values)
        if not np.all(np.isfinite(all_x)):
            return False

        x_min = float(np.min(all_x))
        x_max = float(np.max(all_x))
        if x_min <= 0.0:
            return False

        # AxisItem in log mode internally evaluates 10**range for tick math.
        # Keep domain bounded to avoid overflow in that conversion.
        return x_max < 300.0

    def _layout_has_item(self, item) -> bool:
        layout = self.plot.plotItem.layout
        rows = layout.rowCount()
        cols = layout.columnCount()
        for r in range(rows):
            for c in range(cols):
                if layout.itemAt(r, c) is item:
                    return True
        return False

    def _layout_remove_if_present(self, item) -> None:
        if item is None:
            return
        layout = self.plot.plotItem.layout
        if self._layout_has_item(item):
            try:
                layout.removeItem(item)
            except Exception:
                pass

    def _shift_base_layout(self, target_shift: int) -> None:
        if target_shift == self._base_layout_shift:
            return

        layout = self.plot.plotItem.layout
        delta = target_shift - self._base_layout_shift
        rows = layout.rowCount()
        cols = layout.columnCount()
        custom_axes = set(self._axis_items.values())

        seen_ids: set[int] = set()
        items: list[tuple[object, int, int]] = []
        for r in range(rows):
            for c in range(cols):
                item = layout.itemAt(r, c)
                if item is None or item in custom_axes:
                    continue
                iid = id(item)
                if iid in seen_ids:
                    continue
                seen_ids.add(iid)
                items.append((item, r, c))

        for item, _, _ in items:
            self._layout_remove_if_present(item)

        for item, r, c in items:
            new_c = c + delta
            if new_c < 0:
                new_c = 0
            layout.addItem(item, r, new_c)

        self._base_layout_shift = target_shift
