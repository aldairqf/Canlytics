from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
)

from config.app_config import get_text


class GraphSettingsDialog(QDialog):
    """Simplified graph settings: grid fine-tuning and legend position.

    Grid on/off, legend on/off, and Y-axis mode are ribbon toggles — they are
    not shown here.  This dialog only exposes controls that are too detailed
    for a ribbon button.
    """

    def __init__(
        self,
        *,
        grid_config: dict,
        legend_position: str = "top_left",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(get_text("graph_settings_title"))
        self._build_ui(grid_config=grid_config or {}, legend_position=legend_position)

    def _build_ui(self, *, grid_config: dict, legend_position: str) -> None:
        # ── Grid ──────────────────────────────────────────────────────────────
        self.grid_auto_cb = QCheckBox(get_text("graph_settings_grid_auto"))
        self.grid_auto_cb.setChecked(bool(grid_config.get("auto", True)))

        self.grid_x_enabled_cb = QCheckBox(get_text("graph_settings_grid_x_enabled"))
        self.grid_x_enabled_cb.setChecked(bool(grid_config.get("x_enabled", True)))

        self.grid_y_enabled_cb = QCheckBox(get_text("graph_settings_grid_y_enabled"))
        self.grid_y_enabled_cb.setChecked(bool(grid_config.get("y_enabled", True)))

        self.grid_x_spacing = QDoubleSpinBox()
        self.grid_x_spacing.setRange(0.000001, 1e12)
        self.grid_x_spacing.setDecimals(6)
        self.grid_x_spacing.setValue(float(grid_config.get("x_spacing", 1.0)))

        self.grid_y_spacing = QDoubleSpinBox()
        self.grid_y_spacing.setRange(0.000001, 1e12)
        self.grid_y_spacing.setDecimals(6)
        self.grid_y_spacing.setValue(float(grid_config.get("y_spacing", 1.0)))

        grid_group = QGroupBox(get_text("graph_settings_grid_group"))
        grid_layout = QFormLayout(grid_group)
        grid_layout.addRow(self.grid_auto_cb)
        grid_layout.addRow(self.grid_x_enabled_cb)
        grid_layout.addRow(get_text("graph_settings_grid_x_spacing"), self.grid_x_spacing)
        grid_layout.addRow(self.grid_y_enabled_cb)
        grid_layout.addRow(get_text("graph_settings_grid_y_spacing"), self.grid_y_spacing)

        # ── Legend ────────────────────────────────────────────────────────────
        self.legend_position = QComboBox()
        self.legend_position.addItem(get_text("graph_settings_legend_top_left"), "top_left")
        self.legend_position.addItem(get_text("graph_settings_legend_top_right"), "top_right")
        self.legend_position.addItem(get_text("graph_settings_legend_bottom_left"), "bottom_left")
        self.legend_position.addItem(get_text("graph_settings_legend_bottom_right"), "bottom_right")
        idx = self.legend_position.findData(legend_position)
        self.legend_position.setCurrentIndex(idx if idx >= 0 else 0)

        legend_group = QGroupBox(get_text("graph_settings_legend_group"))
        legend_layout = QFormLayout(legend_group)
        legend_layout.addRow(get_text("graph_settings_legend_position"), self.legend_position)

        # ── Layout ────────────────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(grid_group)
        layout.addWidget(legend_group)
        layout.addWidget(buttons)

        self.grid_auto_cb.toggled.connect(self._sync_spacing_ui)
        self.grid_x_enabled_cb.toggled.connect(self._sync_spacing_ui)
        self.grid_y_enabled_cb.toggled.connect(self._sync_spacing_ui)
        self._sync_spacing_ui()

    def _sync_spacing_ui(self) -> None:
        auto = self.grid_auto_cb.isChecked()
        self.grid_x_spacing.setEnabled(not auto and self.grid_x_enabled_cb.isChecked())
        self.grid_y_spacing.setEnabled(not auto and self.grid_y_enabled_cb.isChecked())

    def get_config(self) -> dict:
        return {
            "grid": {
                "auto": self.grid_auto_cb.isChecked(),
                "x_enabled": self.grid_x_enabled_cb.isChecked(),
                "x_spacing": self.grid_x_spacing.value(),
                "y_enabled": self.grid_y_enabled_cb.isChecked(),
                "y_spacing": self.grid_y_spacing.value(),
            },
            "legend_position": self.legend_position.currentData(),
        }
