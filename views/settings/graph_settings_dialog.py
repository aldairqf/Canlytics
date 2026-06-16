from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)
from PySide6.QtGui import QColor

from config.theme import active_plot_defaults


class GraphSettingsDialog(QDialog):
    def __init__(
        self,
        *,
        y_axis_mode: str,
        grid_config: dict,
        legend_config: dict,
        visual_config: dict,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Graph settings")
        self._build_ui(
            y_axis_mode=y_axis_mode,
            grid_config=grid_config or {},
            legend_config=legend_config or {},
            visual_config=visual_config or {},
        )

    def _build_ui(
        self,
        *,
        y_axis_mode: str,
        grid_config: dict,
        legend_config: dict,
        visual_config: dict,
    ) -> None:
        self.y_axis_mode = QComboBox(self)
        self.y_axis_mode.addItem("Shared Y axis", "shared")
        self.y_axis_mode.addItem("Separate Y axis per signal", "separate")
        self.y_axis_mode.setCurrentIndex(0 if y_axis_mode != "separate" else 1)

        axes_group = QGroupBox("Axes", self)
        axes_layout = QFormLayout(axes_group)
        axes_layout.addRow("Y mode", self.y_axis_mode)

        self.grid_enabled_cb = QCheckBox("Enable grid", self)
        self.grid_enabled_cb.setChecked(bool(grid_config.get("enabled", False)))

        self.grid_auto_cb = QCheckBox("Automatic spacing", self)
        self.grid_auto_cb.setChecked(bool(grid_config.get("auto", True)))

        self.grid_x_enabled_cb = QCheckBox("Show X grid", self)
        self.grid_x_enabled_cb.setChecked(bool(grid_config.get("x_enabled", True)))

        self.grid_y_enabled_cb = QCheckBox("Show Y grid", self)
        self.grid_y_enabled_cb.setChecked(bool(grid_config.get("y_enabled", True)))

        self.grid_x_spacing = QDoubleSpinBox(self)
        self.grid_x_spacing.setRange(0.000001, 1e12)
        self.grid_x_spacing.setDecimals(6)
        self.grid_x_spacing.setValue(float(grid_config.get("x_spacing", 1.0)))

        self.grid_y_spacing = QDoubleSpinBox(self)
        self.grid_y_spacing.setRange(0.000001, 1e12)
        self.grid_y_spacing.setDecimals(6)
        self.grid_y_spacing.setValue(float(grid_config.get("y_spacing", 1.0)))

        grid_group = QGroupBox("Grid", self)
        grid_layout = QFormLayout(grid_group)
        grid_layout.addRow(self.grid_enabled_cb)
        grid_layout.addRow(self.grid_auto_cb)
        grid_layout.addRow(self.grid_x_enabled_cb)
        grid_layout.addRow("X spacing", self.grid_x_spacing)
        grid_layout.addRow(self.grid_y_enabled_cb)
        grid_layout.addRow("Y spacing", self.grid_y_spacing)

        self.legend_show_cb = QCheckBox("Show legend", self)
        self.legend_show_cb.setChecked(bool(legend_config.get("visible", True)))

        self.legend_position = QComboBox(self)
        self.legend_position.addItem("Top left", "top_left")
        self.legend_position.addItem("Top right", "top_right")
        self.legend_position.addItem("Bottom left", "bottom_left")
        self.legend_position.addItem("Bottom right", "bottom_right")
        position = str(legend_config.get("position", "top_left"))
        idx = self.legend_position.findData(position)
        self.legend_position.setCurrentIndex(idx if idx >= 0 else 0)

        self.legend_bg_opacity = QDoubleSpinBox(self)
        self.legend_bg_opacity.setRange(0.0, 1.0)
        self.legend_bg_opacity.setSingleStep(0.05)
        self.legend_bg_opacity.setDecimals(2)
        self.legend_bg_opacity.setValue(float(legend_config.get("bg_opacity", 0.65)))

        self.legend_border_cb = QCheckBox("Show border", self)
        self.legend_border_cb.setChecked(bool(legend_config.get("border", True)))

        legend_group = QGroupBox("Legend", self)
        legend_layout = QFormLayout(legend_group)
        legend_layout.addRow(self.legend_show_cb)
        legend_layout.addRow("Position", self.legend_position)
        legend_layout.addRow("Background opacity", self.legend_bg_opacity)
        legend_layout.addRow(self.legend_border_cb)

        _defaults = active_plot_defaults()
        self.background_color = QColor(str(visual_config.get("background_color", _defaults["background_color"])))
        self.axis_text_color = QColor(str(visual_config.get("axis_text_color", _defaults["axis_text_color"])))
        self.background_color_btn = QPushButton(self)
        self.axis_text_color_btn = QPushButton(self)
        self.background_color_btn.clicked.connect(self._select_background_color)
        self.axis_text_color_btn.clicked.connect(self._select_axis_text_color)
        self._update_color_button(self.background_color_btn, self.background_color)
        self._update_color_button(self.axis_text_color_btn, self.axis_text_color)

        rendering_group = QGroupBox("Rendering", self)
        rendering_layout = QFormLayout(rendering_group)
        rendering_layout.addRow("Background color", self.background_color_btn)
        rendering_layout.addRow("Axis/text color", self.axis_text_color_btn)

        tabs = QTabWidget(self)
        tabs.addTab(self._tab_with_group(axes_group), "Axes")
        tabs.addTab(self._tab_with_group(grid_group), "Grid")
        tabs.addTab(self._tab_with_group(legend_group), "Legend")
        tabs.addTab(self._tab_with_group(rendering_group), "Rendering")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self.grid_enabled_cb.toggled.connect(self._sync_grid_ui)
        self.grid_auto_cb.toggled.connect(self._sync_grid_ui)
        self.grid_x_enabled_cb.toggled.connect(self._sync_grid_ui)
        self.grid_y_enabled_cb.toggled.connect(self._sync_grid_ui)
        self._sync_grid_ui()

    def _tab_with_group(self, group: QGroupBox) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.addWidget(group)
        layout.addStretch(1)
        return container

    def _sync_grid_ui(self) -> None:
        grid_enabled = self.grid_enabled_cb.isChecked()
        auto_spacing = self.grid_auto_cb.isChecked()

        self.grid_auto_cb.setEnabled(grid_enabled)
        self.grid_x_enabled_cb.setEnabled(grid_enabled)
        self.grid_y_enabled_cb.setEnabled(grid_enabled)
        self.grid_x_spacing.setEnabled(grid_enabled and not auto_spacing and self.grid_x_enabled_cb.isChecked())
        self.grid_y_spacing.setEnabled(grid_enabled and not auto_spacing and self.grid_y_enabled_cb.isChecked())

    def get_config(self) -> dict:
        return {
            "y_axis_mode": self.y_axis_mode.currentData(),
            "grid": {
                "enabled": self.grid_enabled_cb.isChecked(),
                "auto": self.grid_auto_cb.isChecked(),
                "x_enabled": self.grid_x_enabled_cb.isChecked(),
                "y_enabled": self.grid_y_enabled_cb.isChecked(),
                "x_spacing": self.grid_x_spacing.value(),
                "y_spacing": self.grid_y_spacing.value(),
            },
            "legend": {
                "visible": self.legend_show_cb.isChecked(),
                "position": self.legend_position.currentData(),
                "bg_opacity": self.legend_bg_opacity.value(),
                "border": self.legend_border_cb.isChecked(),
            },
            "visual": {
                "background_color": self.background_color.name(),
                "axis_text_color": self.axis_text_color.name(),
            },
        }

    def _update_color_button(self, btn: QPushButton, color: QColor) -> None:
        hex_color = color.name()
        r, g, b = color.red(), color.green(), color.blue()
        text_color = "#000000" if (r * 0.299 + g * 0.587 + b * 0.114) > 128 else "#ffffff"
        btn.setStyleSheet(f"background-color: {hex_color}; color: {text_color}; border: 1px solid #888;")
        btn.setText(hex_color)

    def _select_background_color(self) -> None:
        c = QColorDialog.getColor(self.background_color, self)
        if c.isValid():
            self.background_color = c
            self._update_color_button(self.background_color_btn, self.background_color)

    def _select_axis_text_color(self) -> None:
        c = QColorDialog.getColor(self.axis_text_color, self)
        if c.isValid():
            self.axis_text_color = c
            self._update_color_button(self.axis_text_color_btn, self.axis_text_color)
