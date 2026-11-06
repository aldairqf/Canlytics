from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QWidget

from config.app_config import get_text

class StateTrackerDialog(QDialog):
    def __init__(self, can_ids: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(get_text("state_tracker_dialog_title"))
        self._ids = QComboBox(self)
        self._ids.addItems(can_ids)
        self._byte = QSpinBox(self)
        self._byte.setRange(0, 7)
        self._bit = QSpinBox(self)
        self._bit.setRange(0, 7)
        form = QFormLayout(self)
        form.addRow(get_text("state_tracker_can_id"), self._ids)
        form.addRow(get_text("state_tracker_byte"), self._byte)
        form.addRow(get_text("state_tracker_bit"), self._bit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @property
    def selection(self) -> tuple[str, int, int] | None:
        if self._ids.count() == 0:
            return None
        return self._ids.currentText(), self._byte.value(), self._bit.value()
