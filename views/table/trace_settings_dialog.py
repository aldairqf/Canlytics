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
        self.show_j1939_pgn = QCheckBox(get_text("trace_column_j1939_pgn"), self)
        self.show_j1939_sa = QCheckBox(get_text("trace_column_j1939_sa"), self)
        self.show_j1939_da = QCheckBox(get_text("trace_column_j1939_da"), self)
        self.show_j1939_priority = QCheckBox(get_text("trace_column_j1939_priority"), self)
        self.show_j1939_name = QCheckBox(get_text("trace_column_j1939_name"), self)
        self.show_delta_t.setChecked(bool(preferences.get("show_delta_t", False)))
        self.show_name.setChecked(bool(preferences.get("show_name", False)))
        self.show_j1939_pgn.setChecked(bool(preferences.get("show_j1939_pgn", False)))
        self.show_j1939_sa.setChecked(bool(preferences.get("show_j1939_sa", False)))
        self.show_j1939_da.setChecked(bool(preferences.get("show_j1939_da", False)))
        self.show_j1939_priority.setChecked(bool(preferences.get("show_j1939_priority", False)))
        self.show_j1939_name.setChecked(bool(preferences.get("show_j1939_name", False)))
        layout.addWidget(self.show_delta_t)
        layout.addWidget(self.show_name)
        for checkbox in (
            self.show_j1939_pgn,
            self.show_j1939_sa,
            self.show_j1939_da,
            self.show_j1939_priority,
            self.show_j1939_name,
        ):
            layout.addWidget(checkbox)
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
            "show_j1939_pgn": self.show_j1939_pgn.isChecked(),
            "show_j1939_sa": self.show_j1939_sa.isChecked(),
            "show_j1939_da": self.show_j1939_da.isChecked(),
            "show_j1939_priority": self.show_j1939_priority.isChecked(),
            "show_j1939_name": self.show_j1939_name.isChecked(),
        }
