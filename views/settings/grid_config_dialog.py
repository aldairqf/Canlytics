from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
)


class GridConfigDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grid settings")
        self._build_ui(config or {})

    def _build_ui(self, config: dict) -> None:
        self.enabled_cb = QCheckBox("Enable grid", self)
        self.enabled_cb.setChecked(bool(config.get("enabled", False)))

        self.auto_cb = QCheckBox("Automatic spacing", self)
        self.auto_cb.setChecked(bool(config.get("auto", True)))

        axes_group = QGroupBox("Axes", self)
        axes_layout = QFormLayout(axes_group)

        self.x_enabled_cb = QCheckBox("Show X grid", self)
        self.x_enabled_cb.setChecked(bool(config.get("x_enabled", True)))

        self.y_enabled_cb = QCheckBox("Show Y grid", self)
        self.y_enabled_cb.setChecked(bool(config.get("y_enabled", True)))

        self.x_spacing = QDoubleSpinBox(self)
        self.x_spacing.setRange(0.000001, 1e12)
        self.x_spacing.setDecimals(6)
        self.x_spacing.setValue(float(config.get("x_spacing", 1.0)))

        self.y_spacing = QDoubleSpinBox(self)
        self.y_spacing.setRange(0.000001, 1e12)
        self.y_spacing.setDecimals(6)
        self.y_spacing.setValue(float(config.get("y_spacing", 1.0)))

        axes_layout.addRow(self.x_enabled_cb)
        axes_layout.addRow("X spacing", self.x_spacing)
        axes_layout.addRow(self.y_enabled_cb)
        axes_layout.addRow("Y spacing", self.y_spacing)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.enabled_cb)
        layout.addWidget(self.auto_cb)
        layout.addWidget(axes_group)
        layout.addWidget(buttons)

        self.enabled_cb.toggled.connect(self._sync_ui)
        self.auto_cb.toggled.connect(self._sync_ui)
        self.x_enabled_cb.toggled.connect(self._sync_ui)
        self.y_enabled_cb.toggled.connect(self._sync_ui)
        self._sync_ui()

    def _sync_ui(self) -> None:
        grid_enabled = self.enabled_cb.isChecked()
        auto_spacing = self.auto_cb.isChecked()

        self.auto_cb.setEnabled(grid_enabled)
        self.x_enabled_cb.setEnabled(grid_enabled)
        self.y_enabled_cb.setEnabled(grid_enabled)
        self.x_spacing.setEnabled(grid_enabled and not auto_spacing and self.x_enabled_cb.isChecked())
        self.y_spacing.setEnabled(grid_enabled and not auto_spacing and self.y_enabled_cb.isChecked())

    def get_config(self) -> dict:
        return {
            "enabled": self.enabled_cb.isChecked(),
            "auto": self.auto_cb.isChecked(),
            "x_enabled": self.x_enabled_cb.isChecked(),
            "y_enabled": self.y_enabled_cb.isChecked(),
            "x_spacing": self.x_spacing.value(),
            "y_spacing": self.y_spacing.value(),
        }
