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

from config.app_config import get_text
from utils.timezone_format import format_timezone_label


class LogTimezoneDialog(QDialog):
    def __init__(self, *, created_at_text: str, parent=None):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle(get_text("log_timezone_title"))
        self._created_at_text = created_at_text
        self._created_at = datetime.strptime(created_at_text, "%Y-%m-%d %H:%M:%S")

        self._tz_values = _list_timezones()
        self._tz_labels = [format_timezone_label(tz) for tz in self._tz_values]
        self._label_to_value = dict(zip(self._tz_labels, self._tz_values))

        info = QLabel(get_text("log_timezone_info").format(created_at=created_at_text))
        info.setWordWrap(True)

        self.offset_combo = QComboBox()
        self.offset_combo.setEditable(True)
        self.offset_combo.addItems(self._tz_labels)

        completer = QCompleter(self._tz_labels, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.offset_combo.setCompleter(completer)

        if self.offset_combo.lineEdit():
            self.offset_combo.lineEdit().setPlaceholderText(get_text("timezone_search_placeholder"))

        self._set_timezone_text("UTC")

        form = QFormLayout()
        form.addRow(get_text("log_timezone_form_label"), self.offset_combo)

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


