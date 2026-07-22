from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from models.can_send import DbcFrameSource, TransmitEntry
from services.can_send import TransmitEntryError, encode_dbc_payload, resolve_transmit_entry
from views.widgets.hex_byte_row import HexByteRow


class CanSendEntryDialog(QDialog):
    def __init__(self, dbc_manager, entry: TransmitEntry, *, new_entry_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._entry_id = entry.entry_id or new_entry_id
        self._current_message = None
        self._signal_fields: dict[str, QDoubleSpinBox] = {}

        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle(get_text("can_send_entry_dialog_title"))
        self.resize(480, 420)

        self.label_edit = QLineEdit(entry.label)
        self.can_id_edit = QLineEdit(entry.can_id)
        self.extended_check = QCheckBox(get_text("can_send_entry_extended"))
        self.extended_check.setChecked(entry.extended)
        self.dlc_spin = QSpinBox()
        self.dlc_spin.setRange(0, 8)
        self.dlc_spin.setValue(entry.dlc)
        self.dlc_spin.valueChanged.connect(self._on_dlc_changed)

        self.mode_single = QRadioButton(get_text("can_send_entry_mode_single"))
        self.mode_periodic = QRadioButton(get_text("can_send_entry_mode_periodic"))
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.mode_single)
        self._mode_group.addButton(self.mode_periodic)
        (self.mode_periodic if entry.mode == "periodic" else self.mode_single).setChecked(True)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 3_600_000)
        self.interval_spin.setValue(entry.interval_ms)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.mode_single)
        mode_row.addWidget(self.mode_periodic)
        mode_row.addWidget(QLabel(get_text("can_send_entry_interval")))
        mode_row.addWidget(self.interval_spin)
        mode_row.addStretch(1)

        self.source_raw = QRadioButton(get_text("can_send_entry_source_raw"))
        self.source_dbc = QRadioButton(get_text("can_send_entry_source_dbc"))
        self._source_group = QButtonGroup(self)
        self._source_group.setExclusive(True)
        self._source_group.addButton(self.source_raw)
        self._source_group.addButton(self.source_dbc)
        (self.source_dbc if entry.source == "dbc" else self.source_raw).setChecked(True)
        self.source_raw.toggled.connect(self._on_source_toggled)
        self.source_dbc.toggled.connect(lambda _checked: self._on_source_toggled(self.source_raw.isChecked()))
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_raw)
        source_row.addWidget(self.source_dbc)
        source_row.addStretch(1)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_raw_page(entry))
        self.pages.addWidget(self._build_dbc_page(entry))
        self.pages.setCurrentIndex(1 if entry.source == "dbc" else 0)

        form = QFormLayout()
        form.addRow(get_text("can_send_entry_label"), self.label_edit)
        form.addRow(get_text("can_send_entry_can_id"), self.can_id_edit)
        form.addRow("", self.extended_check)
        form.addRow(get_text("can_send_entry_dlc"), self.dlc_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(mode_row)
        layout.addLayout(source_row)
        layout.addWidget(self.pages)
        layout.addStretch(1)
        layout.addWidget(buttons)

        self._on_dlc_changed(entry.dlc)
        if entry.source == "dbc" and entry.dbc_source is not None:
            self._select_dbc_source(entry.dbc_source)

    def _build_raw_page(self, entry: TransmitEntry) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.hex_row = HexByteRow()
        self.hex_row.set_data_hex(entry.data_hex)
        layout.addWidget(self.hex_row)
        layout.addStretch(1)
        return page

    def _build_dbc_page(self, entry: TransmitEntry) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        form = QFormLayout()
        self.dbc_combo = QComboBox()
        self.dbc_combo.addItems(self._dbc_manager.get_dbc_names())
        self.message_combo = QComboBox()
        self.dbc_combo.currentTextChanged.connect(self._on_dbc_changed)
        self.message_combo.currentTextChanged.connect(self._on_message_changed)
        form.addRow(get_text("can_send_entry_dbc_label"), self.dbc_combo)
        form.addRow(get_text("can_send_entry_message_label"), self.message_combo)
        layout.addLayout(form)

        self.signal_form = QFormLayout()
        signal_container = QWidget()
        signal_container.setLayout(self.signal_form)
        layout.addWidget(signal_container)

        apply_btn = QPushButton(get_text("can_send_entry_apply"))
        apply_btn.clicked.connect(self._apply_dbc_values)
        layout.addWidget(apply_btn)
        layout.addStretch(1)

        if self.dbc_combo.count():
            self._on_dbc_changed(self.dbc_combo.currentText())
        return page

    def _on_dlc_changed(self, dlc: int) -> None:
        self.hex_row.set_dlc(dlc)

    def _on_source_toggled(self, raw_checked: bool) -> None:
        self.pages.setCurrentIndex(0 if raw_checked else 1)
        if raw_checked:
            self.can_id_edit.setEnabled(True)
            self.extended_check.setEnabled(True)
            self.dlc_spin.setEnabled(True)
        else:
            self._apply_dbc_message_fields()

    def _apply_dbc_message_fields(self) -> None:
        """Locks/auto-fills the CAN ID/Extended/DLC fields shared with the raw
        page -- only while DBC-assisted is the actually selected source, so
        picking a DBC message doesn't silently overwrite raw-hex mode's
        fields before the user has switched to DBC mode at all."""
        if self._current_message is None or not self.source_dbc.isChecked():
            return
        self.can_id_edit.setText(f"{self._current_message.frame_id:X}")
        self.can_id_edit.setEnabled(False)
        self.extended_check.setChecked(bool(self._current_message.is_extended_frame))
        self.extended_check.setEnabled(False)
        self.dlc_spin.setValue(int(self._current_message.length))
        self.dlc_spin.setEnabled(False)
        if self._current_message.cycle_time:
            self.interval_spin.setValue(int(self._current_message.cycle_time))
            self.mode_periodic.setChecked(True)

    def _on_dbc_changed(self, dbc_name: str) -> None:
        self.message_combo.blockSignals(True)
        self.message_combo.clear()
        if dbc_name:
            self.message_combo.addItems(sorted(m.name for m in self._dbc_manager.get_messages(dbc_name)))
        self.message_combo.blockSignals(False)
        if self.message_combo.count():
            self._on_message_changed(self.message_combo.currentText())

    def _on_message_changed(self, message_name: str) -> None:
        dbc_name = self.dbc_combo.currentText()
        self._current_message = None
        while self.signal_form.rowCount():
            self.signal_form.removeRow(0)
        self._signal_fields = {}
        if not dbc_name or not message_name:
            return
        for message in self._dbc_manager.get_messages(dbc_name):
            if message.name == message_name:
                self._current_message = message
                break
        if self._current_message is None:
            return

        self._apply_dbc_message_fields()

        for signal in self._current_message.signals:
            spin = QDoubleSpinBox()
            minimum = signal.minimum if signal.minimum is not None else -1e12
            maximum = signal.maximum if signal.maximum is not None else 1e12
            spin.setRange(minimum, maximum)
            spin.setDecimals(4)
            spin.setSingleStep(signal.scale or 1.0)
            spin.setValue(signal.minimum if signal.minimum is not None else 0.0)
            label = signal.name + (f" ({signal.unit})" if signal.unit else "")
            self.signal_form.addRow(label, spin)
            self._signal_fields[signal.name] = spin

    def _select_dbc_source(self, dbc_source: DbcFrameSource) -> None:
        index = self.dbc_combo.findText(dbc_source.dbc_name)
        if index < 0:
            return
        self.dbc_combo.setCurrentIndex(index)
        msg_index = self.message_combo.findText(dbc_source.message_name)
        if msg_index >= 0:
            self.message_combo.setCurrentIndex(msg_index)
        for name, value in dbc_source.signal_values.items():
            if name in self._signal_fields:
                self._signal_fields[name].setValue(float(value))

    def _apply_dbc_values(self) -> None:
        if self._current_message is None:
            return
        values = {name: spin.value() for name, spin in self._signal_fields.items()}
        try:
            hex_text = encode_dbc_payload(self._current_message, values)
        except Exception as exc:
            QMessageBox.warning(self, get_text("can_send_entry_invalid"), str(exc))
            return
        self.hex_row.set_data_hex(hex_text)
        self.hex_row.set_dlc(self.dlc_spin.value())

    def _on_accept(self) -> None:
        entry = self.result_entry()
        try:
            resolve_transmit_entry(entry)
        except TransmitEntryError as exc:
            QMessageBox.warning(self, get_text("can_send_entry_invalid"), str(exc))
            return
        self.accept()

    def result_entry(self) -> TransmitEntry:
        source = "dbc" if self.source_dbc.isChecked() else "raw"
        dbc_source = None
        if source == "dbc" and self._current_message is not None:
            dbc_source = DbcFrameSource(
                dbc_name=self.dbc_combo.currentText(),
                message_name=self.message_combo.currentText(),
                signal_values={name: spin.value() for name, spin in self._signal_fields.items()},
            )
        return TransmitEntry(
            entry_id=self._entry_id,
            label=self.label_edit.text().strip(),
            can_id=self.can_id_edit.text().strip().upper(),
            extended=self.extended_check.isChecked(),
            dlc=self.dlc_spin.value(),
            data_hex=self.hex_row.data_hex(self.dlc_spin.value()),
            source=source,
            dbc_source=dbc_source,
            mode="periodic" if self.mode_periodic.isChecked() else "single",
            interval_ms=self.interval_spin.value(),
            enabled=True,
        )
