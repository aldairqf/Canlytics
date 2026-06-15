from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class CursorController:
    def __init__(self, plot_widget, get_plot_data, format_time):
        self.plot = plot_widget
        self._get_plot_data = get_plot_data
        self._format_time = format_time

        self.enabled = False
        self.follow_latest = False
        self.snap_to_sample = True
        self.dual_cursor = False
        self.active_cursor = "A"

        self.show_time = True
        self.show_values = True
        self.show_delta = True

        self.cursor_time: float | None = None
        self.cursor_time_b: float | None = None
        self.cursor_line = self._create_line((200, 200, 200, 180))     # A
        self.cursor_line_b = self._create_line((120, 220, 255, 180))   # B
        self.plot.addItem(self.cursor_line, ignoreBounds=True)
        self.plot.addItem(self.cursor_line_b, ignoreBounds=True)
        self.cursor_line.sigPositionChanged.connect(lambda: self._on_cursor_line_changed("A"))
        self.cursor_line_b.sigPositionChanged.connect(lambda: self._on_cursor_line_changed("B"))
        self._label_a = pg.TextItem(text="A", color=(235, 235, 235), anchor=(0.5, 0.0))
        self._label_b = pg.TextItem(text="B", color=(150, 230, 255), anchor=(0.5, 0.0))
        self.plot.addItem(self._label_a, ignoreBounds=True)
        self.plot.addItem(self._label_b, ignoreBounds=True)
        self._label_a.hide()
        self._label_b.hide()
        vb = self.plot.getViewBox()
        vb.sigRangeChanged.connect(lambda *_: self._on_view_range_changed())

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

    @staticmethod
    def _create_line(color_rgba) -> pg.InfiniteLine:
        line = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen(color=color_rgba, width=1, style=Qt.DashLine),
        )
        line.setVisible(False)
        return line

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.cursor_line.setVisible(False)
            self.cursor_line_b.setVisible(False)
            self._label_a.hide()
            self._label_b.hide()
            self.cursor_time = None
            self.cursor_time_b = None
            self._value_box.hide()
            return
        self.move_to_latest()

    def set_follow_latest(self, enabled: bool) -> None:
        self.follow_latest = enabled
        if enabled and self.enabled:
            self.move_to_latest()

    def set_dual_cursor(self, enabled: bool) -> None:
        self.dual_cursor = bool(enabled)
        if not self.dual_cursor:
            self.cursor_line_b.setVisible(False)
            self._label_b.hide()
            self.cursor_time_b = None
            self.active_cursor = "A"
        elif self.enabled and self.cursor_time is not None and self.cursor_time_b is None:
            self.cursor_time_b = self.cursor_time
            self.cursor_line_b.setValue(self.cursor_time_b)
            self.cursor_line_b.setVisible(True)
            self._label_b.show()
        self.on_redraw()

    def set_active_cursor(self, cursor_name: str) -> None:
        cursor_name = "B" if cursor_name == "B" else "A"
        if cursor_name == "B" and not self.dual_cursor:
            return
        self.active_cursor = cursor_name
        self.on_redraw()

    def set_snap_to_sample(self, enabled: bool) -> None:
        self.snap_to_sample = bool(enabled)
        if not self.enabled:
            return
        plot_data = self._get_plot_data()
        # Apply immediately to all visible cursors so behavior is global/predictable.
        if self.cursor_time is not None:
            self.set_time(self.cursor_time, plot_data=plot_data, force_visible=True, cursor_name="A")
        if self.dual_cursor and self.cursor_time_b is not None:
            self.set_time(self.cursor_time_b, plot_data=plot_data, force_visible=True, cursor_name="B")

    def set_display_options(
        self,
        *,
        show_time: bool | None = None,
        show_values: bool | None = None,
        show_delta: bool | None = None,
    ) -> None:
        if show_time is not None:
            self.show_time = bool(show_time)
        if show_values is not None:
            self.show_values = bool(show_values)
        if show_delta is not None:
            self.show_delta = bool(show_delta)
        self.on_redraw()

    def copy_snapshot_to_clipboard(self) -> None:
        plot_data = self._get_plot_data()
        text = self.snapshot_text(plot_data)
        QGuiApplication.clipboard().setText(text)

    def snapshot_text(self, plot_data: list | None = None) -> str:
        if plot_data is None:
            plot_data = self._get_plot_data()
        if self.cursor_time is None:
            return "Cursor A not set."

        lines: list[str] = []
        lines.append(f"A: {self._format_time(self.cursor_time)} ({self.cursor_time:.9g})")
        if self.dual_cursor and self.cursor_time_b is not None:
            lines.append(f"B: {self._format_time(self.cursor_time_b)} ({self.cursor_time_b:.9g})")
            dt = self.cursor_time_b - self.cursor_time
            lines.append(f"Δt: {dt:.9g}")

        for data in self._visible_only(plot_data):
            xs = np.asarray(data.get("x") or [], dtype=float)
            ys = np.asarray(data.get("y") or [], dtype=float)
            if len(xs) < 2:
                continue
            va = float(np.interp(self.cursor_time, xs, ys))
            vb = float(np.interp(self.cursor_time_b, xs, ys)) if self.cursor_time_b is not None else None
            style = data.get("style", {})
            row = f'{data["label"]}: A={self._format_value(va, style)}'
            if vb is not None:
                row += f", B={self._format_value(vb, style)}, Δ={self._format_value(vb - va, style)}"
            lines.append(row)
        return "\n".join(lines)

    def on_redraw(self) -> None:
        plot_data = self._get_plot_data()
        if not self.enabled:
            return

        if self.follow_latest or self.cursor_time is None:
            self.move_to_latest(plot_data)
            return

        self.set_time(self.cursor_time, plot_data=plot_data, force_visible=True, cursor_name="A")
        if self.dual_cursor:
            if self.cursor_time_b is None:
                self.cursor_time_b = self.cursor_time
            self.set_time(self.cursor_time_b, plot_data=plot_data, force_visible=True, cursor_name="B")
        else:
            self.cursor_line_b.setVisible(False)

    def set_time(
        self,
        t: float,
        plot_data: list | None = None,
        force_visible: bool = False,
        cursor_name: str = "A",
    ) -> None:
        if plot_data is None:
            plot_data = self._get_plot_data()
        t = float(t)
        if self.snap_to_sample:
            t = self._snap_time_to_samples(t, plot_data)

        if cursor_name == "B":
            self.cursor_time_b = t
            self.cursor_line_b.setValue(t)
            if self.enabled or force_visible:
                self.cursor_line_b.setVisible(self.dual_cursor)
                self._label_b.setVisible(self.dual_cursor)
        else:
            self.cursor_time = t
            self.cursor_line.setValue(t)
            if self.enabled or force_visible:
                self.cursor_line.setVisible(True)
                self._label_a.setVisible(True)

        self._update_value_box(plot_data)
        self._update_cursor_bounds()
        self._update_cursor_labels()

    def hide_cursor_line(self) -> None:
        self.cursor_line.setVisible(False)
        self.cursor_line_b.setVisible(False)
        self._label_a.hide()
        self._label_b.hide()

    def has_time(self) -> bool:
        return self.cursor_time is not None

    def nudge_to_next_sample(self, direction: int, plot_data: list | None = None) -> bool:
        if direction == 0:
            return False
        if plot_data is None:
            plot_data = self._get_plot_data()
        xs = self._merged_x_axis(plot_data)
        if xs.size == 0:
            return False

        current = self.cursor_time_b if self.active_cursor == "B" else self.cursor_time
        if current is None:
            idx = xs.size - 1 if direction > 0 else 0
            self.set_time(float(xs[idx]), plot_data=plot_data, force_visible=True, cursor_name=self.active_cursor)
            return True

        if direction > 0:
            idx = int(np.searchsorted(xs, current, side="right"))
            if idx >= xs.size:
                idx = xs.size - 1
        else:
            idx = int(np.searchsorted(xs, current, side="left") - 1)
            if idx < 0:
                idx = 0

        self.set_time(float(xs[idx]), plot_data=plot_data, force_visible=True, cursor_name=self.active_cursor)
        return True

    def values_text(self, t: float, plot_data: list) -> str:
        lines = [f"Time: {self._format_time(t)}"]
        for data in self._visible_only(plot_data):
            xs = np.asarray(data["x"], dtype=float)
            ys = np.asarray(data["y"], dtype=float)
            if len(xs) < 2:
                continue
            value = float(np.interp(t, xs, ys))
            lines.append(f'{data["label"]}: {self._format_value(value, data.get("style", {}))}')
        return "\n".join(lines)

    def position_value_box(self) -> None:
        margin = 12
        width = 320
        self._value_box.resize(width, max(90, self._value_box.sizeHint().height()))
        self._value_box.move(self.plot.width() - width - margin, margin)

    @staticmethod
    def _visible_only(plot_data: list) -> list:
        return [d for d in plot_data if d.get("style", {}).get("visible", True)]

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

    def move_to_latest(self, plot_data: list | None = None) -> None:
        if plot_data is None:
            plot_data = self._get_plot_data()
        latest_x = self._latest_x(self._visible_only(plot_data))
        if latest_x is None:
            self.cursor_line.setVisible(False)
            self.cursor_line_b.setVisible(False)
            self._label_a.hide()
            self._label_b.hide()
            self._value_box.hide()
            return
        self.set_time(latest_x, plot_data=plot_data, force_visible=True, cursor_name="A")
        if self.dual_cursor:
            self.set_time(latest_x, plot_data=plot_data, force_visible=True, cursor_name="B")

    def _merged_x_axis(self, plot_data: list) -> np.ndarray:
        chunks: list[np.ndarray] = []
        for data in self._visible_only(plot_data):
            xs = data.get("x") or []
            if not xs:
                continue
            arr = np.asarray(xs, dtype=float)
            if arr.size:
                chunks.append(arr)
        if not chunks:
            return np.asarray([], dtype=float)
        return np.unique(np.concatenate(chunks))

    def _snap_time_to_samples(self, t: float, plot_data: list) -> float:
        xs = self._merged_x_axis(plot_data)
        if xs.size == 0:
            return t
        idx = int(np.searchsorted(xs, t, side="left"))
        if idx <= 0:
            return float(xs[0])
        if idx >= xs.size:
            return float(xs[-1])
        left = xs[idx - 1]
        right = xs[idx]
        return float(left if abs(t - left) <= abs(right - t) else right)

    def playback_values_html(self, t: float, plot_data: list) -> str:
        lines: list[str] = []
        colors: list[str] = []
        for data in self._visible_only(plot_data):
            xs = np.asarray(data["x"], dtype=float)
            ys = np.asarray(data["y"], dtype=float)
            if len(xs) < 2:
                continue
            value = float(np.interp(t, xs, ys))
            lines.append(self._format_value(value, data.get("style", {})))
            c = data["style"]["color"]
            colors.append(c.name() if hasattr(c, "name") else str(c))
        return "".join(
            f'<span style="color:{c};">{l}</span>&nbsp;&nbsp;'
            for l, c in zip(lines, colors)
        )

    def _on_cursor_line_changed(self, cursor_name: str) -> None:
        if not self.enabled:
            return
        line = self.cursor_line_b if cursor_name == "B" else self.cursor_line
        t = self._clamp_to_visible_x(float(line.value()))
        if t != float(line.value()):
            line.setValue(t)
        if self.snap_to_sample:
            t = self._snap_time_to_samples(t, self._get_plot_data())
            t = self._clamp_to_visible_x(t)
            line.setValue(t)

        if cursor_name == "B":
            self.cursor_time_b = t
        else:
            self.cursor_time = t

        self._update_value_box(self._get_plot_data())
        self._update_cursor_bounds()
        self._update_cursor_labels()

    def _update_value_box(self, plot_data: list) -> None:
        if not plot_data or self.cursor_time is None:
            self._value_box.hide()
            return

        rows: list[str] = []
        t_a = self.cursor_time
        t_b = self.cursor_time_b if self.dual_cursor else None

        if self.show_time:
            rows.append(f'<div style="font-weight:700; color:#d8d8d8;">A: {self._format_time(t_a)}</div>')
            if t_b is not None:
                rows.append(f'<div style="font-weight:700; color:#b7e8ff;">B: {self._format_time(t_b)}</div>')

        if self.show_delta and t_b is not None:
            dt = t_b - t_a
            rows.append(f'<div style="margin-top:4px; color:#f5d08a;">Δt: {dt:.9g}</div>')

        for data in self._visible_only(plot_data):
            xs = np.asarray(data["x"], dtype=float)
            ys = np.asarray(data["y"], dtype=float)
            if len(xs) < 2:
                continue
            style = data.get("style", {})
            color = style.get("color")
            color_name = color.name() if hasattr(color, "name") else str(color)

            v_a = float(np.interp(t_a, xs, ys))
            value_chunk: list[str] = []
            if self.show_values:
                value_chunk.append(f"A={self._format_value(v_a, style)}")
            if t_b is not None:
                v_b = float(np.interp(t_b, xs, ys))
                if self.show_values:
                    value_chunk.append(f"B={self._format_value(v_b, style)}")
                if self.show_delta:
                    value_chunk.append(f"Δ={self._format_value(v_b - v_a, style)}")

            if not value_chunk:
                continue
            rows.append(
                "<div style=\"margin-top:4px;\">"
                f'<span style="color:{color_name}; font-weight:600;">{data["label"]}:</span> '
                f'<span style="color:#f3f3f3;">{" | ".join(value_chunk)}</span>'
                "</div>"
            )

        if not rows:
            self._value_box.hide()
            return

        self._value_box_label.setText("".join(rows))
        self._value_box.adjustSize()
        self.position_value_box()
        self._value_box.show()

    def _on_view_range_changed(self) -> None:
        self._update_cursor_bounds()
        self._update_cursor_labels()

    def _visible_x_range(self) -> tuple[float, float]:
        x_range = self.plot.getViewBox().viewRange()[0]
        return float(x_range[0]), float(x_range[1])

    def _clamp_to_visible_x(self, t: float) -> float:
        x0, x1 = self._visible_x_range()
        if x0 > x1:
            x0, x1 = x1, x0
        return float(max(x0, min(x1, t)))

    def _update_cursor_bounds(self) -> None:
        x0, x1 = self._visible_x_range()
        if x0 > x1:
            x0, x1 = x1, x0
        self.cursor_line.setBounds((x0, x1))
        self.cursor_line_b.setBounds((x0, x1))

    def _update_cursor_labels(self) -> None:
        y_range = self.plot.getViewBox().viewRange()[1]
        y_top = float(max(y_range))
        y_pad = (float(max(y_range)) - float(min(y_range))) * 0.02
        y = y_top - y_pad
        if self.enabled and self.cursor_time is not None and self.cursor_line.isVisible():
            self._label_a.setPos(float(self.cursor_time), y)
            self._label_a.show()
        else:
            self._label_a.hide()

        if (
            self.enabled
            and self.dual_cursor
            and self.cursor_time_b is not None
            and self.cursor_line_b.isVisible()
        ):
            self._label_b.setPos(float(self.cursor_time_b), y)
            self._label_b.show()
        else:
            self._label_b.hide()

    @staticmethod
    def _format_value(value: float, style: dict) -> str:
        mode = str(style.get("value_format", "auto") or "auto").lower()
        decimals = int(style.get("value_decimals", 6))
        decimals = max(0, min(12, decimals))
        unit = str(style.get("value_unit", "") or "").strip()

        if mode == "fixed":
            text = f"{value:.{decimals}f}"
        elif mode == "scientific":
            text = f"{value:.{decimals}e}"
        else:
            precision = max(1, decimals)
            text = f"{value:.{precision}g}"

        return f"{text} {unit}".strip()
