from __future__ import annotations

from PySide6.QtCore import QRegularExpression, QSignalBlocker, QTimer, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from config.app_config import get_text
from models.trace_filter import TraceFilter


class TraceFilterBar(QWidget):
    filters_changed = Signal(object)
    data_mode_changed = Signal(str)
    columns_settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(get_text("trace_filter_byte"), self))
        self.byte = QComboBox(self)
        self.byte.addItem(get_text("trace_filter_any"), None)
        for index in range(8):
            self.byte.addItem(str(index), index)
        self.byte.setToolTip(get_text("trace_filter_byte_tooltip"))
        layout.addWidget(self.byte)
        layout.addWidget(QLabel(get_text("trace_filter_mask"), self))
        self.mask = self._hex_input(self)
        self.mask.setPlaceholderText("FF")
        self.mask.setToolTip(get_text("trace_filter_mask_tooltip"))
        layout.addWidget(self.mask)
        layout.addWidget(QLabel(get_text("trace_filter_value"), self))
        self.value = self._hex_input(self)
        self.value.setPlaceholderText("--")
        self.value.setToolTip(get_text("trace_filter_value_tooltip"))
        layout.addWidget(self.value)
        layout.addWidget(QLabel(get_text("trace_filter_dlc"), self))
        self.dlc = QComboBox(self)
        self.dlc.addItem(get_text("trace_filter_any"), None)
        for length in range(9):
            self.dlc.addItem(str(length), length)
        self.dlc.setToolTip(get_text("trace_filter_dlc_tooltip"))
        layout.addWidget(self.dlc)
        self.only_changes = QCheckBox(get_text("trace_filter_only_changes"), self)
        layout.addWidget(self.only_changes)
        self.clear_button = QPushButton(get_text("trace_filter_clear"), self)
        layout.addWidget(self.clear_button)
        self.data_mode = QComboBox(self)
        for label_key, mode in (("trace_display_hex", "hex"), ("trace_display_dec", "dec"), ("trace_display_bits", "bits")):
            self.data_mode.addItem(get_text(label_key), mode)
        self.data_mode.setToolTip(get_text("trace_display_mode_tooltip"))
        layout.addWidget(self.data_mode)
        self.columns_button = QPushButton(get_text("trace_columns_button"), self)
        layout.addWidget(self.columns_button)
        layout.addStretch(1)
        self.byte.currentIndexChanged.connect(self._schedule_filter)
        self.dlc.currentIndexChanged.connect(self._schedule_filter)
        self.mask.textChanged.connect(self._schedule_filter)
        self.value.textChanged.connect(self._schedule_filter)
        self.only_changes.toggled.connect(self._schedule_filter)
        self.clear_button.clicked.connect(self.clear)
        self.data_mode.currentIndexChanged.connect(
            lambda _index: self.data_mode_changed.emit(str(self.data_mode.currentData()))
        )
        self.columns_button.clicked.connect(self.columns_settings_requested.emit)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(180)
        self._filter_timer.timeout.connect(self._emit_filter_now)

    def set_data_mode(self, mode: str) -> None:
        index = self.data_mode.findData(mode)
        self.data_mode.setCurrentIndex(index if index >= 0 else self.data_mode.findData("hex"))

    @staticmethod
    def _hex_input(parent: QWidget) -> QLineEdit:
        edit = QLineEdit(parent)
        edit.setMaximumWidth(54)
        edit.setMaxLength(2)
        edit.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{0,2}"), edit))
        return edit

    def clear(self) -> None:
        blockers = [QSignalBlocker(widget) for widget in (self.byte, self.mask, self.value, self.dlc, self.only_changes)]
        self.byte.setCurrentIndex(0)
        self.mask.clear()
        self.value.clear()
        self.dlc.setCurrentIndex(0)
        self.only_changes.setChecked(False)
        del blockers
        self._filter_timer.stop()
        self._emit_filter_now()

    def _schedule_filter(self, *_args: object) -> None:
        self._filter_timer.start()

    def _emit_filter_now(self) -> None:
        mask_text = self.mask.text().strip()
        value_text = self.value.text().strip()
        self.filters_changed.emit(
            TraceFilter(
                byte_index=self.byte.currentData(),
                mask=int(mask_text, 16) if mask_text else None,
                value=int(value_text, 16) if value_text else None,
                dlc=self.dlc.currentData(),
                only_changes=self.only_changes.isChecked(),
            )
        )
