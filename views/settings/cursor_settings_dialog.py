from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QRadioButton,
    QVBoxLayout,
)

from config.app_config import get_text


class CursorSettingsDialog(QDialog):
    def __init__(self, config: dict[str, bool | str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(get_text("cursor_settings_title"))
        self.setModal(True)

        self.enabled = QCheckBox(get_text("cursor_enabled"), self)
        self.enabled.setChecked(bool(config.get("enabled", False)))

        self.follow_latest = QCheckBox(get_text("cursor_follow_latest"), self)
        self.follow_latest.setChecked(bool(config.get("follow_latest", False)))

        self.snap_to_sample = QCheckBox(get_text("cursor_snap_to_sample"), self)
        self.snap_to_sample.setChecked(bool(config.get("snap_to_sample", True)))

        behavior_group = QGroupBox(get_text("cursor_behavior_group"), self)
        behavior_layout = QFormLayout(behavior_group)
        behavior_layout.addRow(self.enabled)
        behavior_layout.addRow(self.follow_latest)
        behavior_layout.addRow(self.snap_to_sample)

        self.dual_cursor = QCheckBox(get_text("cursor_dual"), self)
        self.dual_cursor.setChecked(bool(config.get("dual_cursor", False)))

        self.active_a = QRadioButton(get_text("cursor_a"), self)
        self.active_b = QRadioButton(get_text("cursor_b"), self)
        active_cursor = str(config.get("active_cursor", "A"))
        self.active_a.setChecked(active_cursor != "B")
        self.active_b.setChecked(active_cursor == "B")

        active_layout = QHBoxLayout()
        active_layout.addWidget(self.active_a)
        active_layout.addWidget(self.active_b)

        cursor_group = QGroupBox(get_text("cursor_mode_group"), self)
        cursor_layout = QFormLayout(cursor_group)
        cursor_layout.addRow(self.dual_cursor)
        cursor_layout.addRow(get_text("cursor_active"), active_layout)

        self.show_time = QCheckBox(get_text("cursor_show_time"), self)
        self.show_time.setChecked(bool(config.get("show_time", True)))
        self.show_values = QCheckBox(get_text("cursor_show_values"), self)
        self.show_values.setChecked(bool(config.get("show_values", True)))
        self.show_delta = QCheckBox(get_text("cursor_show_delta"), self)
        self.show_delta.setChecked(bool(config.get("show_delta", True)))

        display_group = QGroupBox(get_text("cursor_display_group"), self)
        display_layout = QFormLayout(display_group)
        display_layout.addRow(self.show_time)
        display_layout.addRow(self.show_values)
        display_layout.addRow(self.show_delta)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(behavior_group)
        layout.addWidget(cursor_group)
        layout.addWidget(display_group)
        layout.addWidget(buttons)

        self.enabled.toggled.connect(self._refresh_enabled_state)
        self.dual_cursor.toggled.connect(self._refresh_enabled_state)
        self._refresh_enabled_state()

    def get_config(self) -> dict[str, bool | str]:
        return {
            "enabled": self.enabled.isChecked(),
            "follow_latest": self.follow_latest.isChecked(),
            "snap_to_sample": self.snap_to_sample.isChecked(),
            "dual_cursor": self.dual_cursor.isChecked(),
            "active_cursor": "B" if self.active_b.isChecked() else "A",
            "show_time": self.show_time.isChecked(),
            "show_values": self.show_values.isChecked(),
            "show_delta": self.show_delta.isChecked(),
        }

    def _refresh_enabled_state(self) -> None:
        enabled = self.enabled.isChecked()
        dual = enabled and self.dual_cursor.isChecked()
        for widget in (
            self.follow_latest,
            self.snap_to_sample,
            self.dual_cursor,
            self.active_a,
            self.show_time,
            self.show_values,
            self.show_delta,
        ):
            widget.setEnabled(enabled)
        self.active_b.setEnabled(dual)
        self.show_delta.setEnabled(dual)
        if not dual and self.active_b.isChecked():
            self.active_a.setChecked(True)
