from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt, Signal as QtSignal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from utils.can_bytes import byte_value_to_hex, parse_hex_bytes

_BYTE_COUNT = 8


class HexByteRow(QWidget):
    """Eight validated 2-digit hex byte inputs (D0..D7) for building a raw CAN
    payload. Extra bytes beyond the current DLC are disabled rather than
    hidden, so toggling DLC doesn't discard already-typed values."""

    changed = QtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._fields: list[QLineEdit] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        validator = QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{0,2}"))
        for _ in range(_BYTE_COUNT):
            field = QLineEdit("00")
            field.setMaxLength(2)
            field.setFixedWidth(28)
            field.setValidator(validator)
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.textChanged.connect(lambda _text: self.changed.emit())
            layout.addWidget(field)
            self._fields.append(field)

    def set_dlc(self, dlc: int) -> None:
        for index, field in enumerate(self._fields):
            field.setEnabled(index < dlc)

    def set_data_hex(self, data_hex: str) -> None:
        data = parse_hex_bytes(data_hex)
        for index, field in enumerate(self._fields):
            value = data[index] if index < len(data) else None
            field.blockSignals(True)
            field.setText(byte_value_to_hex(value) or "00")
            field.blockSignals(False)

    def data_hex(self, dlc: int) -> str:
        parts = []
        for index in range(dlc):
            text = self._fields[index].text().strip() or "00"
            if len(text) == 1:
                text = "0" + text
            parts.append(text)
        return "".join(parts).upper()
