from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from config.app_config import get_text


class TraceSettingsDialog(QDialog):
    def __init__(self, preferences: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(get_text("trace_columns_title"))
        layout = QVBoxLayout(self)
        self.show_delta_t = QCheckBox(get_text("trace_column_delta_t"), self)
        self.show_name = QCheckBox(get_text("trace_column_name"), self)
        self.show_delta_t.setChecked(bool(preferences.get("show_delta_t", False)))
        self.show_name.setChecked(bool(preferences.get("show_name", False)))
        layout.addWidget(self.show_delta_t)
        layout.addWidget(self.show_name)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def preferences(self) -> dict[str, bool]:
        return {
            "show_delta_t": self.show_delta_t.isChecked(),
            "show_name": self.show_name.isChecked(),
        }
