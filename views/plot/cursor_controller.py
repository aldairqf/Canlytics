import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class CursorController:
    def __init__(self, plot_widget, get_plot_data, format_time):
        self.plot = plot_widget
        self._get_plot_data = get_plot_data
        self._format_time = format_time

        self.enabled = False
        self.follow_latest = False
        self.cursor_time: float | None = None

        self.cursor_line = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen(color=(200, 200, 200, 160), width=1, style=Qt.DashLine),
        )
        self.cursor_line.setVisible(False)
        self.plot.addItem(self.cursor_line)
        self.cursor_line.sigPositionChanged.connect(self._on_cursor_line_changed)

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

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.cursor_line.setVisible(False)
            self.cursor_time = None
            self._value_box.hide()
            return
        self.move_to_latest()

    def set_follow_latest(self, enabled: bool) -> None:
        self.follow_latest = enabled
        if enabled and self.enabled:
            self.move_to_latest()

    def on_redraw(self) -> None:
        plot_data = self._get_plot_data()
        if self.enabled:
            if self.follow_latest or self.cursor_time is None:
                self.move_to_latest(plot_data)
            else:
                self.set_time(self.cursor_time, plot_data=plot_data, force_visible=True)

    def set_time(self, t: float, plot_data: list | None = None, force_visible: bool = False) -> None:
        if plot_data is None:
            plot_data = self._get_plot_data()
        self.cursor_time = float(t)
        self.cursor_line.setValue(self.cursor_time)
        if self.enabled or force_visible:
            self.cursor_line.setVisible(True)
        self._update_value_box(self.cursor_time, plot_data)

    def hide_cursor_line(self) -> None:
        self.cursor_line.setVisible(False)

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

        if self.cursor_time is None:
            idx = xs.size - 1 if direction > 0 else 0
            self.set_time(float(xs[idx]), plot_data=plot_data, force_visible=True)
            return True

        if direction > 0:
            idx = int(np.searchsorted(xs, self.cursor_time, side="right"))
            if idx >= xs.size:
                idx = xs.size - 1
        else:
            idx = int(np.searchsorted(xs, self.cursor_time, side="left") - 1)
            if idx < 0:
                idx = 0
        self.set_time(float(xs[idx]), plot_data=plot_data, force_visible=True)
        return True

    def values_text(self, t: float, plot_data: list) -> str:
        lines = [f"Time: {self._format_time(t)}"]
        for data in plot_data:
            xs = np.asarray(data["x"], dtype=float)
            ys = np.asarray(data["y"], dtype=float)
            if len(xs) < 2:
                continue
            value = float(np.interp(t, xs, ys))
            lines.append(f'{data["label"]}: {self._format_value(value, data.get("style", {}))}')
        return "\n".join(lines)

    def position_value_box(self) -> None:
        margin = 12
        width = 280
        self._value_box.resize(width, max(80, self._value_box.sizeHint().height()))
        self._value_box.move(self.plot.width() - width - margin, margin)

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
        latest_x = self._latest_x(plot_data)
        if latest_x is None:
            self.cursor_line.setVisible(False)
            self._value_box.hide()
            return
        self.set_time(latest_x, plot_data=plot_data, force_visible=True)

    @staticmethod
    def _merged_x_axis(plot_data: list) -> np.ndarray:
        chunks: list[np.ndarray] = []
        for data in plot_data:
            xs = data.get("x") or []
            if not xs:
                continue
            arr = np.asarray(xs, dtype=float)
            if arr.size:
                chunks.append(arr)
        if not chunks:
            return np.asarray([], dtype=float)
        return np.unique(np.concatenate(chunks))

    def playback_values_html(self, t: float, plot_data: list) -> str:
        lines: list[str] = []
        colors: list[str] = []
        for data in plot_data:
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

    def _on_cursor_line_changed(self) -> None:
        if not self.enabled:
            return
        self.cursor_time = float(self.cursor_line.value())
        plot_data = self._get_plot_data()
        self._update_value_box(self.cursor_time, plot_data)

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
            value_text = self._format_value(value, data.get("style", {}))
            rows.append(
                "<div style=\"margin-top:4px;\">"
                f'<span style="color:{color_name}; font-weight:600;">{data["label"]}:</span> '
                f'<span style="color:#f3f3f3;">{value_text}</span>'
                "</div>"
            )

        if not rows:
            self._value_box.hide()
            return

        ts = self._format_time(t)
        html = (
            f'<div style="font-weight:700; color:#d8d8d8; margin-bottom:6px;">{ts}</div>'
            + "".join(rows)
        )
        self._value_box_label.setText(html)
        self._value_box.adjustSize()
        self.position_value_box()
        self._value_box.show()

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
