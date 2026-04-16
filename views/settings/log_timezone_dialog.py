from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)


class LogTimezoneDialog(QDialog):
    def __init__(self, *, created_at_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UTC of Recording")

        self._offsets = _build_utc_offsets()

        info = QLabel(
            "This log contains a local recording start time without timezone.\n"
            f"Start time found: {created_at_text}\n"
            "Select the UTC offset used when the log was recorded."
        )
        info.setWordWrap(True)

        self.offset_combo = QComboBox()
        self.offset_combo.addItems(list(self._offsets.keys()))
        self.offset_combo.setCurrentText("UTC+00:00")

        form = QFormLayout()
        form.addRow("UTC offset", self.offset_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @property
    def offset_minutes(self) -> int:
        return self._offsets.get(self.offset_combo.currentText(), 0)


def _build_utc_offsets() -> dict[str, int]:
    values: dict[str, int] = {}
    for minutes in range(-12 * 60, 14 * 60 + 1, 30):
        sign = "+" if minutes >= 0 else "-"
        abs_minutes = abs(minutes)
        hours, mins = divmod(abs_minutes, 60)
        values[f"UTC{sign}{hours:02d}:{mins:02d}"] = minutes
    return values
