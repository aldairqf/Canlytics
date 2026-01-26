from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QGridLayout,
    QRadioButton,
    QLineEdit,
    QPushButton,
)
from PySide6.QtCore import Qt

from core.dbc_manager import DbcManager
from core.frame_selector import FrameSelector
from core.signal import Signal


class DecodeTab(QWidget):
    def __init__(self, df, dbc_manager: DbcManager | None = None):
        super().__init__()
        self.df = df
        self.dbc_manager = dbc_manager
        self._dbc_signal_guard = False

        self._selector_mode: str = "exact"
        self._selector_pgn: int | None = None
        self._selector_target_id: int | None = None

        self._build_ui()
        self._update_bit_matrix()
        self._refresh_dbc_options()

    def _build_ui(self):
        layout = QHBoxLayout(self)

        left_column = QVBoxLayout()
        left_column.addWidget(self._build_dbc_group())
        left_column.addStretch()

        right_column = QVBoxLayout()
        right_column.addWidget(self._build_decode_group())

        layout.addLayout(left_column, 1)
        layout.addLayout(right_column, 2)

    def _all_log_ids(self) -> list[str]:
        if self.df is None or self.df.is_empty():
            return []
        return sorted(self.df["ID"].unique().to_list())

    def _filter_log_ids_exact(self, target_can_id_hex: str) -> list[str]:
        try:
            target = int(target_can_id_hex, 16)
        except ValueError:
            return []
        out = []
        for s in self._all_log_ids():
            try:
                if int(s, 16) == target:
                    out.append(s)
            except ValueError:
                continue
        return sorted(out)

    def _filter_log_ids_j1939(self, pgn: int) -> list[str]:
        out = []
        for s in self._all_log_ids():
            try:
                cid = int(s, 16)
            except ValueError:
                continue
            if ((cid // 256) % (1 << 18)) == pgn:
                out.append(s)
        return sorted(out)

    def _build_dbc_group(self):
        box = QGroupBox("DBC")
        layout = QVBoxLayout(box)
        form = QFormLayout()

        self.dbc_status = QLabel("No DBC loaded")
        self.dbc_status.setStyleSheet("color: #999;")

        self.dbc_box = QComboBox()
        self.dbc_box.currentIndexChanged.connect(self._on_dbc_changed)

        self.message_box = QComboBox()
        self.message_box.currentIndexChanged.connect(self._on_message_changed)

        self.signal_box = QComboBox()

        self.param_box = QComboBox()
        self.param_box.addItems(["Scaled", "Raw"])

        form.addRow(self.dbc_status)
        form.addRow("DBC", self.dbc_box)
        form.addRow("Message", self.message_box)
        form.addRow("Signal", self.signal_box)
        form.addRow("Value", self.param_box)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("GetDecode")
        self.apply_btn.clicked.connect(self._on_apply_dbc_clicked)

        self.show_all_btn = QPushButton("Show all IDs")
        self.show_all_btn.clicked.connect(self._on_show_all_ids_clicked)

        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.show_all_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        if self.dbc_manager:
            self.dbc_manager.entries_changed.connect(self._refresh_dbc_options)

        return box

    def _build_decode_group(self):
        box = QGroupBox("CAN decode")
        layout = QVBoxLayout(box)
        form = QFormLayout()

        self.name_edit = QLineEdit()

        self.id_box = QComboBox()
        self.id_box.addItems(self._all_log_ids())

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
        bits: list[int] = []

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
                lbl.setStyleSheet("background-color: #3daee9; border: 1px solid #555;")

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

    def _refresh_dbc_options(self):
        if not self.dbc_manager:
            self.dbc_status.setVisible(True)
            self.apply_btn.setEnabled(False)
            self.dbc_box.setEnabled(False)
            self.message_box.setEnabled(False)
            self.signal_box.setEnabled(False)
            self.param_box.setEnabled(False)
            return

        dbc_names = self.dbc_manager.get_dbc_names(active_only=True)
        self.dbc_box.blockSignals(True)
        self.dbc_box.clear()
        self.dbc_box.addItems(dbc_names)
        self.dbc_box.blockSignals(False)

        has_dbc = bool(dbc_names)
        self.dbc_status.setVisible(not has_dbc)
        self.apply_btn.setEnabled(has_dbc)
        self.dbc_box.setEnabled(has_dbc)
        self.message_box.setEnabled(has_dbc)
        self.signal_box.setEnabled(has_dbc)
        self.param_box.setEnabled(has_dbc)

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
        for sig in signals:
            display = f"{sig} ({dbc_name} / {message_name})"
            self.signal_box.addItem(display, sig)
        self.signal_box.blockSignals(False)

    def _on_apply_dbc_clicked(self):
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
            self._selector_mode = signal_data.get("id_match", "exact")
            self._selector_pgn = signal_data.get("pgn")
            self._selector_target_id = None
            if self._selector_mode == "exact":
                try:
                    self._selector_target_id = int(str(signal_data.get("can_id") or ""), 16)
                except ValueError:
                    self._selector_target_id = None

            self.name_edit.setText(signal_data["name"])
            self.start_bit.setValue(int(signal_data["start_bit"]))
            self.length.setValue(int(signal_data["length"]))
            self.le.setChecked(bool(signal_data["le"]))
            self.be.setChecked(not bool(signal_data["le"]))
            self.type_data.setCurrentText(str(signal_data["type_data"]))
            self.scale.setValue(float(signal_data["scale"]))
            self.offset.setValue(float(signal_data["offset"]))
            self.mux_start.setValue(int(signal_data["mux_start"]))
            self.mux_bytes.setValue(int(signal_data["mux_bytes"]))
            self._on_mux_bytes_changed(int(signal_data["mux_bytes"]))
            mux_value = signal_data["mux_value"]
            self.mux_value.setText("" if mux_value is None else str(mux_value))
            self._update_bit_matrix()

            prev = self.id_box.currentText().strip() or None
            valid_ids: list[str] = []
            if self._selector_mode == "j1939":
                if self._selector_pgn is not None:
                    valid_ids = self._filter_log_ids_j1939(int(self._selector_pgn))
            else:
                valid_ids = self._filter_log_ids_exact(str(signal_data.get("can_id") or ""))

            self.id_box.blockSignals(True)
            self.id_box.clear()
            self.id_box.addItems(valid_ids)
            self.id_box.blockSignals(False)

            if prev in valid_ids:
                self.id_box.setCurrentText(prev)
            elif valid_ids:
                self.id_box.setCurrentText(valid_ids[0])
            else:
                self.id_box.setCurrentText("")
        finally:
            self._dbc_signal_guard = False

    def _on_show_all_ids_clicked(self):
        prev = self.id_box.currentText().strip() or None
        ids = self._all_log_ids()
        self.id_box.blockSignals(True)
        self.id_box.clear()
        self.id_box.addItems(ids)
        self.id_box.blockSignals(False)
        if prev in ids:
            self.id_box.setCurrentText(prev)

    def get_signal_data(self) -> dict:
        mux_value_text = self.mux_value.text().strip() or None
        selected_id = self.id_box.currentText().strip() or None

        signal = {
            "name": self.name_edit.text().strip(),
            "can_id": selected_id,
            "start_bit": self.start_bit.value(),
            "length": self.length.value(),
            "le": self.le.isChecked(),
            "scale": self.scale.value(),
            "offset": self.offset.value(),
            "mux_start": self.mux_start.value(),
            "mux_bytes": self.mux_bytes.value(),
            "mux_value": mux_value_text,
            "type_data": self.type_data.currentText().strip(),
        }

        selector = {
            "selected_id": selected_id,
            "mode": self._selector_mode,
            "pgn": self._selector_pgn,
            "target_id": self._selector_target_id,
        }

        return {"signal": signal, "selector": selector}

    def load_signal(
        self,
        signal: Signal,
        *,
        selector: FrameSelector | None = None,
    ):
        selector = selector or FrameSelector()

        self._selector_mode = selector.mode or "exact"
        self._selector_pgn = selector.pgn
        self._selector_target_id = selector.target_id

        self.name_edit.setText(signal.name)

        self._on_show_all_ids_clicked()
        desired_id = signal.can_id or selector.selected_id
        if desired_id:
            self.id_box.setCurrentText(desired_id)

        self.start_bit.setValue(signal.start_bit)
        self.length.setValue(signal.length)
        self.le.setChecked(signal.le)
        self.be.setChecked(not signal.le)
        self.scale.setValue(signal.scale)
        self.offset.setValue(signal.offset)
        self.mux_start.setValue(signal.mux_start)
        self.mux_bytes.setValue(signal.mux_bytes)
        self._on_mux_bytes_changed(signal.mux_bytes)
        self.mux_value.setText("" if signal.mux_bytes == 0 else str(signal.mux_value or ""))
        self.type_data.setCurrentText(signal.type_data)

        self._update_bit_matrix()
