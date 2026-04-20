from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
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
        self._created_at_text = created_at_text
        self._created_at = datetime.strptime(created_at_text, "%Y-%m-%d %H:%M:%S")

        self._tz_values = _list_timezones()
        self._tz_labels = [_format_timezone_label(tz) for tz in self._tz_values]
        self._label_to_value = dict(zip(self._tz_labels, self._tz_values))

        info = QLabel(
            "This log contains a local recording start time without timezone.\n"
            f"Start time found: {created_at_text}\n"
            "Select the timezone used when the log was recorded."
        )
        info.setWordWrap(True)

        self.offset_combo = QComboBox()
        self.offset_combo.setEditable(True)
        self.offset_combo.addItems(self._tz_labels)

        completer = QCompleter(self._tz_labels, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.offset_combo.setCompleter(completer)

        if self.offset_combo.lineEdit():
            self.offset_combo.lineEdit().setPlaceholderText("Search timezone (e.g. UTC, America/Lima)")

        self._set_timezone_text("UTC")

        form = QFormLayout()
        form.addRow("Timezone", self.offset_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @property
    def offset_minutes(self) -> int:
        tz = self._selected_timezone()
        if not tz:
            return 0

        if tz == "UTC":
            return 0

        try:
            offset = self._created_at.replace(tzinfo=ZoneInfo(tz)).utcoffset()
        except ZoneInfoNotFoundError:
            return 0

        if offset is None:
            return 0
        return int(offset.total_seconds() // 60)

    @property
    def timezone_name(self) -> str:
        tz = self._selected_timezone()
        return tz or "UTC"

    def _set_timezone_text(self, tz: str) -> None:
        try:
            idx = self._tz_values.index(tz)
            self.offset_combo.setCurrentIndex(idx)
        except ValueError:
            self.offset_combo.setCurrentText(tz)

    def _selected_timezone(self) -> str:
        text = (self.offset_combo.currentText() or "").strip()
        return self._label_to_value.get(text, text)


def _list_timezones() -> list[str]:
    zones = sorted(available_timezones())
    if "UTC" in zones:
        zones.remove("UTC")
    return ["UTC"] + zones


def _format_timezone_label(tz: str) -> str:
    if tz == "UTC":
        return "UTC (UTC+00:00)"

    try:
        offset = datetime.now(ZoneInfo(tz)).utcoffset()
    except ZoneInfoNotFoundError:
        return tz

    if offset is None:
        return tz

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    abs_minutes = abs(total_minutes)
    hours, minutes = divmod(abs_minutes, 60)
    return f"{tz} (UTC{sign}{hours:02d}:{minutes:02d})"
