from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
)

from viewmodels.time_config_viewmodel import TimeConfigViewModel
from utils.timezone_format import format_timezone_label


class TimeConfigDialog(QDialog):
    def __init__(self, vm: TimeConfigViewModel, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TimeConfig")
        self._vm = vm

        self.normalize_cb = QCheckBox("Normalize timestamp")
        self.tz_combo = QComboBox()
        self.tz_combo.setEditable(True)

        self._tz_values = ["none"] + self._vm.list_timezones()
        self._tz_labels = ["Raw seconds"] + [format_timezone_label(tz) for tz in self._vm.list_timezones()]
        self._label_to_value = dict(zip(self._tz_labels, self._tz_values))

        self.tz_combo.addItems(self._tz_labels)

        completer = QCompleter(self._tz_labels, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.tz_combo.setCompleter(completer)

        if self.tz_combo.lineEdit():
            self.tz_combo.lineEdit().setPlaceholderText("Search timezone (e.g. UTC, America/Lima)")

        form = QFormLayout()
        form.addRow(self.normalize_cb)
        form.addRow("Timezone", self.tz_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._load_from_vm()
        self.normalize_cb.toggled.connect(self._on_normalize_toggled)

    def _load_from_vm(self) -> None:
        self.normalize_cb.setChecked(self._vm.normalize)
        self._set_timezone_text(self._vm.timezone)
        self._apply_normalize_ui(self._vm.normalize)

    def _set_timezone_text(self, tz: str) -> None:
        tz = (tz or "none").strip()
        if tz == "none":
            self.tz_combo.setCurrentIndex(0)
            return
        try:
            idx = self._tz_values.index(tz)
            self.tz_combo.setCurrentIndex(idx)
        except ValueError:
            self.tz_combo.setCurrentText(tz)

    def _on_normalize_toggled(self, checked: bool) -> None:
        self._apply_normalize_ui(checked)
        if checked:
            self.tz_combo.setCurrentIndex(0)

    def _apply_normalize_ui(self, normalize: bool) -> None:
        self.tz_combo.setEnabled(not normalize)

    def accept(self) -> None:
        normalize = self.normalize_cb.isChecked()

        text = (self.tz_combo.currentText() or "").strip()
        if not text or text.lower() == "none" or text.lower() == "raw seconds":
            tz = "none"
        else:
            tz = self._label_to_value.get(text, text)

        self._vm.apply(normalize=normalize, timezone=tz)
        super().accept()
