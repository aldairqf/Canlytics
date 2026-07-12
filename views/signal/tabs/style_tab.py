from PySide6.QtWidgets import (
    QWidget, QFormLayout, QGroupBox,
    QPushButton, QComboBox, QSpinBox, QCheckBox, QLineEdit,
    QColorDialog
)
from PySide6.QtGui import QColor

from config.app_config import get_option, get_text
from config.theme import get_active_theme
from utils.plot_sampling import MARKER_MAX_PTS

class StyleTab(QWidget):
    def __init__(self, initial_color: QColor | None = None):
        super().__init__()
        self.color = initial_color or QColor("cyan")
        self.marker_color = QColor(self.color)
        self.marker_enabled = False
        self._build_ui()
        self._update_color_btn()
        self._update_marker_color_btn()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.addWidget(self._build_style_group())

    def _build_style_group(self):
        box = QGroupBox(get_text("graph_style_title"))
        form = QFormLayout(box)

        self.color_btn = QPushButton(get_text("select_color"))
        self.color_btn.clicked.connect(self._select_color)

        self.line_style = QComboBox()
        self.line_style.addItems(get_option("line_styles", []))

        self.line_width = QSpinBox()
        self.line_width.setRange(1, 5)
        self.line_width.setValue(2)

        self.value_format = QComboBox()
        self.value_format.addItem("Auto", "auto")
        self.value_format.addItem("Fixed decimals", "fixed")
        self.value_format.addItem("Scientific", "scientific")

        self.value_decimals = QSpinBox()
        self.value_decimals.setRange(0, 12)
        self.value_decimals.setValue(6)

        self.value_unit = QLineEdit()
        self.value_unit.setPlaceholderText(get_text("style_value_unit_placeholder"))

        self.marker_enabled_cb = QCheckBox()
        self.marker_enabled_cb.setChecked(False)
        self.step_mode_cb = QCheckBox()
        self.step_mode_cb.setChecked(False)

        self.marker_shape = QComboBox()
        self.marker_shape.addItems(get_option("marker_shapes", []))

        self.marker_size = QSpinBox()
        self.marker_size.setRange(1, 20)
        self.marker_size.setValue(8)

        self.marker_max_points = QSpinBox()
        self.marker_max_points.setRange(100, 200000)
        self.marker_max_points.setSingleStep(500)
        self.marker_max_points.setValue(MARKER_MAX_PTS)
        self.marker_max_points.setToolTip(get_text("marker_max_points_tooltip"))

        self.marker_color_btn = QPushButton(get_text("select_color"))
        self.marker_color_btn.clicked.connect(self._select_marker_color)

        form.addRow(get_text("color_label"), self.color_btn)
        form.addRow(get_text("line_style_label"), self.line_style)
        form.addRow(get_text("line_width_label"), self.line_width)
        form.addRow(get_text("style_value_format_label"), self.value_format)
        form.addRow(get_text("style_decimals_label"), self.value_decimals)
        form.addRow(get_text("style_unit_label"), self.value_unit)
        form.addRow(get_text("style_step_mode_label"), self.step_mode_cb)
        form.addRow(get_text("marker_enabled_label"), self.marker_enabled_cb)
        form.addRow(get_text("marker_shape_label"), self.marker_shape)
        form.addRow(get_text("marker_size_label"), self.marker_size)
        form.addRow(get_text("marker_max_points_label"), self.marker_max_points)
        form.addRow(get_text("marker_color_label"), self.marker_color_btn)

        return box

    def _update_color_btn(self):
        hex_color = self.color.name()
        r, g, b = self.color.red(), self.color.green(), self.color.blue()
        text_color = "#000000" if (r * 0.299 + g * 0.587 + b * 0.114) > 128 else "#ffffff"
        self.color_btn.setStyleSheet(
            f"background-color: {hex_color}; color: {text_color}; border: 1px solid {get_active_theme().border};"
        )
        self.color_btn.setText(hex_color)

    def _select_color(self):
        c = QColorDialog.getColor(self.color, self)
        if c.isValid():
            self.color = c
            self._update_color_btn()

    def _update_marker_color_btn(self):
        hex_color = self.marker_color.name()
        r, g, b = self.marker_color.red(), self.marker_color.green(), self.marker_color.blue()
        text_color = "#000000" if (r * 0.299 + g * 0.587 + b * 0.114) > 128 else "#ffffff"
        self.marker_color_btn.setStyleSheet(
            f"background-color: {hex_color}; color: {text_color}; border: 1px solid {get_active_theme().border};"
        )
        self.marker_color_btn.setText(hex_color)

    def _select_marker_color(self):
        c = QColorDialog.getColor(self.marker_color, self)
        if c.isValid():
            self.marker_color = c
            self._update_marker_color_btn()

    def load_signal(self, view_signal):
        self.color = view_signal.color
        self._update_color_btn()
        self.line_style.setCurrentText(view_signal.line_style)
        self.line_width.setValue(view_signal.line_width)
        mode = str(getattr(view_signal, "value_format", "auto"))
        idx = self.value_format.findData(mode)
        self.value_format.setCurrentIndex(idx if idx >= 0 else 0)
        self.value_decimals.setValue(int(getattr(view_signal, "value_decimals", 6)))
        self.value_unit.setText(str(getattr(view_signal, "value_unit", "")))
        self.step_mode_cb.setChecked(bool(getattr(view_signal, "step_mode", False)))
        self.marker_enabled_cb.setChecked(bool(getattr(view_signal, "marker_enabled", False)))
        self.marker_shape.setCurrentText(getattr(view_signal, "marker_shape", "Circle"))
        self.marker_size.setValue(int(getattr(view_signal, "marker_size", 8)))
        self.marker_max_points.setValue(int(getattr(view_signal, "marker_max_points", MARKER_MAX_PTS)))
        self.marker_color = QColor(getattr(view_signal, "marker_color", self.color))
        self._update_marker_color_btn()

    def get_style(self):
        return {
            "color": self.color,
            "line_style": self.line_style.currentText(),
            "line_width": self.line_width.value(),
            "value_format": self.value_format.currentData(),
            "value_decimals": self.value_decimals.value(),
            "value_unit": self.value_unit.text().strip(),
            "step_mode": self.step_mode_cb.isChecked(),
            "marker_enabled": self.marker_enabled_cb.isChecked(),
            "marker_shape": self.marker_shape.currentText(),
            "marker_size": self.marker_size.value(),
            "marker_max_points": self.marker_max_points.value(),
            "marker_color": self.marker_color,
            "marker_border_color": self.marker_color,
            "marker_border_width": 0,
        }
