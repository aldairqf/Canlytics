from __future__ import annotations

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from models.analysis_context import AnalysisContext


class SaveSignalDialog(QDialog):
    """Collect a signal definition prefilled from an analysis context."""

    save_requested = QtSignal(object)

    def __init__(
        self,
        context: AnalysisContext,
        defaults: dict[str, object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("save_signal_title"))
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        source = context.source_window or get_text("analysis_context_source_unknown")
        mux_context = (
            get_text("save_signal_source_mux_case").format(value=context.mux_case)
            if context.mux_case is not None else ""
        )
        self.source_label = QLabel(
            get_text("save_signal_source").format(
                source=source, can_id=context.can_id or "—", mux_case=mux_context,
            ),
            self,
        )
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)

        form = QFormLayout()
        layout.addLayout(form)
        self.can_id = QLineEdit(str(context.can_id or ""), self)
        self.can_id.setObjectName("saveSignalCanId")
        self.can_id.setReadOnly(True)
        form.addRow(get_text("save_signal_can_id"), self.can_id)

        self.message_name = QLineEdit(str(defaults.get("message_name") or ""), self)
        self.message_name.setReadOnly(bool(defaults.get("working_message")))
        form.addRow(get_text("save_signal_message_name"), self.message_name)
        self.message_length = QSpinBox(self)
        self.message_length.setRange(1, 8)
        self.message_length.setValue(int(defaults.get("message_length") or 8))
        self.message_length.setReadOnly(bool(defaults.get("existing_message")))
        form.addRow(get_text("save_signal_message_length"), self.message_length)

        start, length, little_endian = context.suggested_signal_geometry()
        suffix = f"{start}_{length}"
        self.signal_name = QLineEdit(
            str(defaults.get("signal_name") or f"Signal_{context.can_id or 'CAN'}_{suffix}"), self
        )
        self.signal_name.setObjectName("saveSignalName")
        form.addRow(get_text("save_signal_name"), self.signal_name)
        self.start = QSpinBox(self)
        self.start.setRange(0, 63)
        self.start.setValue(start)
        form.addRow(get_text("save_signal_start"), self.start)
        self.length = QSpinBox(self)
        self.length.setRange(1, 64)
        self.length.setValue(length)
        form.addRow(get_text("save_signal_length"), self.length)

        self.byte_order = QComboBox(self)
        self.byte_order.addItem(get_text("save_signal_little_endian"), "little_endian")
        self.byte_order.addItem(get_text("save_signal_big_endian"), "big_endian")
        self.byte_order.setCurrentIndex(0 if little_endian else 1)
        form.addRow(get_text("save_signal_byte_order"), self.byte_order)
        self.is_signed = QCheckBox(self)
        self.is_signed.setChecked(bool(defaults.get("is_signed", False)))
        form.addRow(get_text("save_signal_signed"), self.is_signed)
        self.scale = self._make_double(defaults.get("scale", 1.0))
        form.addRow(get_text("save_signal_scale"), self.scale)
        self.offset = self._make_double(defaults.get("offset", 0.0))
        form.addRow(get_text("save_signal_offset"), self.offset)
        self.unit = QLineEdit(str(defaults.get("unit") or ""), self)
        form.addRow(get_text("save_signal_unit"), self.unit)
        self.minimum = QLineEdit(self._optional_text(defaults.get("minimum")), self)
        form.addRow(get_text("save_signal_minimum"), self.minimum)
        self.maximum = QLineEdit(self._optional_text(defaults.get("maximum")), self)
        form.addRow(get_text("save_signal_maximum"), self.maximum)
        self.is_float = QCheckBox(self)
        self.is_float.setChecked(bool(defaults.get("is_float", False)))
        form.addRow(get_text("save_signal_float"), self.is_float)

        self.is_multiplexer = QCheckBox(self)
        self.is_multiplexer.setChecked(bool(defaults.get("is_multiplexer", False)))
        form.addRow(get_text("save_signal_is_multiplexer"), self.is_multiplexer)
        self.multiplexer_signal = QComboBox(self)
        self.multiplexer_signal.setEditable(True)
        self.multiplexer_signal.addItem("")
        multiplexer_signals = list(defaults.get("multiplexer_signals") or [])
        self.multiplexer_signal.addItems(multiplexer_signals)
        selected_mux = defaults.get("multiplexer_signal")
        if not selected_mux and context.mux_case is not None and multiplexer_signals:
            selected_mux = multiplexer_signals[0]
        self.multiplexer_signal.setCurrentText(str(selected_mux or ""))
        form.addRow(get_text("save_signal_multiplexer"), self.multiplexer_signal)
        mux_default = defaults.get("multiplexer_ids")
        if mux_default is None and selected_mux and isinstance(context.mux_case, int):
            mux_default = [context.mux_case]
        mux_text = ", ".join(str(value) for value in mux_default or [])
        self.multiplexer_ids = QLineEdit(mux_text, self)
        self.multiplexer_ids.setToolTip(get_text("save_signal_multiplexer_ids_tooltip"))
        form.addRow(get_text("save_signal_multiplexer_ids"), self.multiplexer_ids)

        self.comment = QLineEdit(str(defaults.get("comment") or ""), self)
        form.addRow(get_text("save_signal_comment"), self.comment)
        self.error_label = QLabel(self)
        self.error_label.setObjectName("saveSignalError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        self.buttons.accepted.connect(self._submit)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    @staticmethod
    def _make_double(value: object) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setRange(-1_000_000_000_000.0, 1_000_000_000_000.0)
        field.setDecimals(9)
        field.setValue(float(value))
        return field

    @staticmethod
    def _optional_text(value: object) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def _optional_float(field: QLineEdit, label: str) -> float | None:
        value = field.text().strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(get_text("save_signal_invalid_number").format(field=label)) from exc

    def _submit(self) -> None:
        try:
            can_id = self.can_id.text().strip().upper().removeprefix("0X")
            try:
                frame_id = int(can_id, 16)
            except ValueError as exc:
                raise ValueError(get_text("save_signal_invalid_can_id")) from exc
            if not 0 <= frame_id <= 0x1FFFFFFF:
                raise ValueError(get_text("save_signal_invalid_can_id"))
            signal_name = self.signal_name.text().strip()
            if not signal_name:
                raise ValueError(get_text("save_signal_name_required"))
            try:
                mux_ids = [
                    int(value.strip(), 10)
                    for value in self.multiplexer_ids.text().split(",")
                    if value.strip()
                ]
            except ValueError as exc:
                raise ValueError(get_text("save_signal_invalid_mux_id")) from exc
            params = {
                "can_id": can_id,
                "message_name": self.message_name.text().strip() or None,
                "message_length": self.message_length.value(),
                "signal_name": signal_name,
                "start": self.start.value(),
                "length": self.length.value(),
                "byte_order": self.byte_order.currentData(),
                "is_signed": self.is_signed.isChecked(),
                "scale": self.scale.value(),
                "offset": self.offset.value(),
                "unit": self.unit.text().strip() or None,
                "minimum": self._optional_float(self.minimum, get_text("save_signal_minimum")),
                "maximum": self._optional_float(self.maximum, get_text("save_signal_maximum")),
                "is_float": self.is_float.isChecked(),
                "is_multiplexer": self.is_multiplexer.isChecked(),
                "multiplexer_signal": self.multiplexer_signal.currentText().strip() or None,
                "multiplexer_ids": mux_ids or None,
                "comment": self.comment.text().strip() or None,
            }
        except (ValueError, OverflowError) as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.error_label.clear()
        self.error_label.hide()
        self.save_requested.emit(params)

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()
