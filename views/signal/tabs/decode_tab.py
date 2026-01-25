from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QLabel, QGridLayout,
    QRadioButton, QLineEdit
)
from PySide6.QtCore import Qt

from core.dbc_manager import DbcManager


class DecodeTab(QWidget):
    def __init__(self, df, dbc_manager: DbcManager | None = None):
        super().__init__()
        self.df = df
        self.dbc_manager = dbc_manager
        self._dbc_signal_guard = False
        self._dbc_id_match = "exact"
        self._dbc_pgn = None

        self._build_ui()
        self._update_bit_matrix()

    def _build_ui(self):
        layout = QHBoxLayout(self)

        left_column = QVBoxLayout()
        left_column.addWidget(self._build_source_group())
        left_column.addWidget(self._build_dbc_group())
        left_column.addStretch()

        right_column = QVBoxLayout()
        right_column.addWidget(self._build_decode_group())

        layout.addLayout(left_column, 1)
        layout.addLayout(right_column, 2)

    def _build_source_group(self):
        box = QGroupBox("Source")
        layout = QHBoxLayout(box)

        self.source_manual = QRadioButton("Manual")
        self.source_dbc = QRadioButton("DBC")

        self.source_manual.setChecked(True)
        self.source_manual.toggled.connect(self._on_source_toggled)

        layout.addWidget(self.source_manual)
        layout.addWidget(self.source_dbc)
        layout.addStretch()

        return box

    def _build_dbc_group(self):
        box = QGroupBox("DBC")
        layout = QFormLayout(box)

        self.dbc_status = QLabel("No DBC loaded")
        self.dbc_status.setStyleSheet("color: #999;")

        self.dbc_box = QComboBox()
        self.dbc_box.currentIndexChanged.connect(self._on_dbc_changed)

        self.message_box = QComboBox()
        self.message_box.currentIndexChanged.connect(self._on_message_changed)

        self.signal_box = QComboBox()
        self.signal_box.currentIndexChanged.connect(self._on_signal_changed)

        self.param_box = QComboBox()
        self.param_box.addItems(["Scaled", "Raw"])
        self.param_box.currentIndexChanged.connect(self._on_signal_changed)

        layout.addRow(self.dbc_status)
        layout.addRow("DBC", self.dbc_box)
        layout.addRow("Message", self.message_box)
        layout.addRow("Signal", self.signal_box)
        layout.addRow("Value", self.param_box)

        if self.dbc_manager:
            self.dbc_manager.entries_changed.connect(self._refresh_dbc_options)
        self._refresh_dbc_options()

        return box

    def _build_decode_group(self):
        box = QGroupBox("CAN decode")
        layout = QVBoxLayout(box)
        form = QFormLayout()

        self.name_edit = QLineEdit()

        self.id_box = QComboBox()
        if self.df is not None and not self.df.is_empty():
            self.id_box.addItems(sorted(self.df["ID"].unique().to_list()))

        self.start_bit = QSpinBox()
        self.start_bit.setRange(0, 63)
        self.start_bit.valueChanged.connect(self._update_bit_matrix)

        self.length = QSpinBox()
        self.length.setRange(1, 64)
        self.length.setValue(8)
        self.length.valueChanged.connect(self._on_length_changed)

        self.le = QRadioButton("Little Endian")
        self.be = QRadioButton("Big Endian")
        self.le.setChecked(True)
        self.le.toggled.connect(self._update_bit_matrix)

        endian_layout = QHBoxLayout()
        endian_layout.addWidget(self.le)
        endian_layout.addWidget(self.be)

        self.type_data = QComboBox()
        self.type_data.addItems(["uint", "int", "float32"])
        self.type_data.setCurrentText("uint")

        self.scale = QDoubleSpinBox()
        self.scale.setDecimals(6)
        self.scale.setValue(1.0)
        self.scale.setMaximum(1e9)

        self.offset = QDoubleSpinBox()
        self.offset.setDecimals(6)
        self.offset.setValue(0.0)
        self.offset.setMaximum(1e9)
        self.offset.setMinimum(-1e9)

        self.mux_start = QSpinBox()
        self.mux_start.setRange(0, 7)

        self.mux_bytes = QSpinBox()
        self.mux_bytes.setRange(0, 8)
        self.mux_bytes.valueChanged.connect(self._on_mux_bytes_changed)

        self.mux_value = QLineEdit()
        self.mux_value.setEnabled(False)

        index = self.type_data.findText("float32")
        if index >= 0:
            self.type_data.model().item(index).setEnabled(self.length.value() == 32)

        form.addRow("Signal name", self.name_edit)
        form.addRow("CAN ID", self.id_box)
        form.addRow("Start bit", self.start_bit)
        form.addRow("Length", self.length)
        form.addRow("Endianness", endian_layout)
        form.addRow("Data type", self.type_data)
        form.addRow("Scale", self.scale)
        form.addRow("Offset", self.offset)
        form.addRow("MUX Start", self.mux_start)
        form.addRow("MUX bytes", self.mux_bytes)
        form.addRow("MUX value", self.mux_value)

        layout.addLayout(form)
        layout.addWidget(self._build_bit_matrix())

        return box

    def _build_bit_matrix(self):
        self.matrix = QGridLayout()
        self.bit_labels = {}

        for bit in range(7, -1, -1):
            self.matrix.addWidget(QLabel(str(bit)), 0, 7 - bit + 1)

        for byte in range(8):
            self.matrix.addWidget(QLabel(f"B{byte}"), byte + 1, 0)

        for byte in range(8):
            for bit in range(8):
                lbl = QLabel(" ")
                lbl.setFixedSize(20, 20)
                lbl.setStyleSheet("border: 1px solid #555;")
                lbl.setAlignment(Qt.AlignCenter)
                self.matrix.addWidget(lbl, byte + 1, bit + 1)
                self.bit_labels[(byte, bit)] = lbl

        container = QWidget()
        container.setLayout(self.matrix)
        return container

    def _update_bit_matrix(self):
        if not hasattr(self, "bit_labels"):
            return

        for lbl in self.bit_labels.values():
            lbl.setStyleSheet("border: 1px solid #555;")

        start = self.start_bit.value()
        length = self.length.value()
        bits = []

        if self.le.isChecked():
            byte = start // 8
            bit_in_byte = start % 8
            for _ in range(length):
                if byte >= 8:
                    break
                bits.append(byte * 8 + bit_in_byte)
                bit_in_byte += 1
                if bit_in_byte > 7:
                    bit_in_byte = 0
                    byte += 1
        else:
            byte = start // 8
            bit_in_byte = start % 8
            for _ in range(length):
                if byte >= 8:
                    break
                bits.append(byte * 8 + bit_in_byte)
                bit_in_byte -= 1
                if bit_in_byte < 0:
                    bit_in_byte = 7
                    byte += 1

        for bit in bits:
            byte = bit // 8
            col = 7 - (bit % 8)
            lbl = self.bit_labels.get((byte, col))
            if lbl:
                lbl.setStyleSheet(
                    "background-color: #3daee9; border: 1px solid #555;"
                )
                
    def _on_length_changed(self, value: int):
        index = self.type_data.findText("float32")
        if index >= 0:
            self.type_data.model().item(index).setEnabled(value == 32)

        if value != 32 and self.type_data.currentText() == "float32":
            self.type_data.setCurrentText("uint")

        self._update_bit_matrix()

    def _on_mux_bytes_changed(self, value: int):
        if value == 0:
            self.mux_value.setEnabled(False)
            self.mux_value.setText("")
        else:
            self.mux_value.setEnabled(True)

    def get_name(self) -> str:
        return self.name_edit.text().strip()

    def _on_source_toggled(self):
        use_manual = self.source_manual.isChecked()
        self._set_manual_enabled(use_manual)
        self._set_dbc_enabled(not use_manual)
        if not use_manual:
            self._apply_selected_dbc_signal()

    def _set_manual_enabled(self, enabled: bool):
        widgets = [
            self.name_edit,
            self.id_box,
            self.start_bit,
            self.length,
            self.le,
            self.be,
            self.type_data,
            self.scale,
            self.offset,
            self.mux_start,
            self.mux_bytes,
            self.mux_value,
        ]
        for widget in widgets:
            widget.setEnabled(enabled)
        for lbl in self.bit_labels.values():
            lbl.setEnabled(enabled)

    def _set_dbc_enabled(self, enabled: bool):
        self.dbc_box.setEnabled(enabled)
        self.message_box.setEnabled(enabled)
        self.signal_box.setEnabled(enabled)
        self.param_box.setEnabled(enabled)

    def _refresh_dbc_options(self):
        if not self.dbc_manager:
            self.dbc_status.setVisible(True)
            self.source_dbc.setEnabled(False)
            self._set_dbc_enabled(False)
            return

        dbc_names = self.dbc_manager.get_dbc_names(active_only=True)
        self.dbc_box.blockSignals(True)
        self.dbc_box.clear()
        self.dbc_box.addItems(dbc_names)
        self.dbc_box.blockSignals(False)

        has_dbc = bool(dbc_names)
        self.dbc_status.setVisible(not has_dbc)
        self.source_dbc.setEnabled(has_dbc)
        self._set_dbc_enabled(has_dbc and not self.source_manual.isChecked())
        if has_dbc:
            self._on_dbc_changed()

    def _on_dbc_changed(self):
        if not self.dbc_manager:
            return
        dbc_name = self.dbc_box.currentText()
        messages = self.dbc_manager.get_message_names(dbc_name)
        self.message_box.blockSignals(True)
        self.message_box.clear()
        self.message_box.addItems(messages)
        self.message_box.blockSignals(False)
        self._on_message_changed()

    def _on_message_changed(self):
        if not self.dbc_manager:
            return
        dbc_name = self.dbc_box.currentText()
        message_name = self.message_box.currentText()
        signals = self.dbc_manager.get_signal_names(dbc_name, message_name)
        self.signal_box.blockSignals(True)
        self.signal_box.clear()
        for signal in signals:
            display = f"{signal} ({dbc_name} / {message_name})"
            self.signal_box.addItem(display, signal)
        self.signal_box.blockSignals(False)
        self._on_signal_changed()

    def _on_signal_changed(self):
        if self._dbc_signal_guard:
            return
        if self.source_manual.isChecked():
            return
        self._apply_selected_dbc_signal()

    def _apply_selected_dbc_signal(self):
        if not self.dbc_manager:
            return
        dbc_name = self.dbc_box.currentText()
        message_name = self.message_box.currentText()
        signal_name = self.signal_box.currentData() or self.signal_box.currentText()
        if not dbc_name or not message_name or not signal_name:
            return
        scaled = self.param_box.currentText() == "Scaled"
        signal_data = self.dbc_manager.get_signal_definition(
            dbc_name,
            message_name,
            signal_name,
            scaled=scaled,
        )
        self._dbc_signal_guard = True
        try:
            self._dbc_id_match = signal_data.get("id_match", "exact")
            self._dbc_pgn = signal_data.get("pgn")
            self.name_edit.setText(signal_data["name"])
            can_id = signal_data["can_id"]
            if self.id_box.findText(can_id) == -1:
                self.id_box.addItem(can_id)
            self.id_box.setCurrentText(can_id)
            self.start_bit.setValue(signal_data["start_bit"])
            self.length.setValue(signal_data["length"])
            self.le.setChecked(signal_data["le"])
            self.be.setChecked(not signal_data["le"])
            self.type_data.setCurrentText(signal_data["type_data"])
            self.scale.setValue(signal_data["scale"])
            self.offset.setValue(signal_data["offset"])
            self.mux_start.setValue(signal_data["mux_start"])
            self.mux_bytes.setValue(signal_data["mux_bytes"])
            self._on_mux_bytes_changed(signal_data["mux_bytes"])
            mux_value = signal_data["mux_value"]
            self.mux_value.setText("" if mux_value is None else str(mux_value))
            self._update_bit_matrix()
        finally:
            self._dbc_signal_guard = False

    def get_signal_data(self) -> dict:
        match_mode = "exact"
        pgn = None
        if self.source_dbc.isChecked():
            match_mode = self._dbc_id_match
            pgn = self._dbc_pgn
        return {
            "name": self.name_edit.text().strip(),
            "can_id": self.id_box.currentText(),
            "id_match": match_mode,
            "pgn": pgn,
            "start_bit": self.start_bit.value(),
            "length": self.length.value(),
            "le": self.le.isChecked(),
            "scale": self.scale.value(),
            "offset": self.offset.value(),
            "mux_start": self.mux_start.value(),
            "mux_bytes": self.mux_bytes.value(),
            "mux_value": self.mux_value.text().strip() or None,
            "type_data": self.type_data.currentText().strip(),
        }


    def load_signal(self, signal):
        self.name_edit.setText(signal.name)
        self.id_box.setCurrentText(signal.can_id)
        self.start_bit.setValue(signal.start_bit)
        self.length.setValue(signal.length)
        self.le.setChecked(signal.le)
        self.be.setChecked(not signal.le)
        self.scale.setValue(signal.scale)
        self.offset.setValue(signal.offset)
        self.mux_start.setValue(signal.mux_start)
        self.mux_bytes.setValue(signal.mux_bytes)
        self._on_mux_bytes_changed(signal.mux_bytes)
        self.mux_value.setText("" if signal.mux_bytes == 0 else str(signal.mux_value))
        self.type_data.setCurrentText(signal.type_data)

        self._update_bit_matrix()
