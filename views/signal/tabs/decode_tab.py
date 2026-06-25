from __future__ import annotations

import polars as pl

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
    QToolButton,
    QScrollArea,
)


from PySide6.QtGui import QValidator


class _TrimmedDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that strips trailing zeros and evaluates simple expressions.

    Accepts plain numbers and arithmetic expressions like ``1/0.6`` or ``2*pi``.
    """

    def textFromValue(self, value: float) -> str:
        text = f"{value:.{self.decimals()}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    def valueFromText(self, text: str) -> float:
        try:
            result = float(eval(text, {"__builtins__": {}}, {"pi": 3.141592653589793}))  # noqa: S307
        except Exception:
            return self.value()
        return max(self.minimum(), min(self.maximum(), result))

    def validate(self, text: str, pos: int):
        # Accept any non-empty input while typing; full evaluation happens on commit.
        if text.strip():
            return QValidator.State.Acceptable, text, pos
        return QValidator.State.Intermediate, text, pos
from PySide6.QtCore import Qt

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.dbc_manager import DbcManager
from services.pgn_scanner import available_bam_pgns, available_j1939_pgns
from config.app_config import get_option, get_text
from config.theme import get_active_theme
from views.icons import icon
from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_to_int


class DecodeTab(QWidget):
    def __init__(self, df, dbc_manager: DbcManager | None = None):
        super().__init__()
        self.df = df
        self.dbc_manager = dbc_manager
        self._dbc_signal_guard = False
        self._matrix_n_bytes: int = -1
        self._pick_mode: str | None = None

        self._selector_mode: str = "exact"
        self._selector_pgn: int | None = None
        self._selector_target_id: int | None = None

        self._build_ui()
        self.dbc_panel = self._build_dbc_group()
        self._update_bit_matrix()
        self._refresh_dbc_options()

    def _build_ui(self):
        layout = QHBoxLayout(self)

        self._matrix_scroll = QScrollArea()
        self._matrix_scroll.setWidgetResizable(True)
        self._matrix_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._matrix_scroll.setMinimumWidth(190)
        layout.addWidget(self._matrix_scroll, 1)

        right_column = QVBoxLayout()
        right_column.addWidget(self._build_decode_group())
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


    @staticmethod
    def _extract_j1939_pgn(cid: int) -> int:
        dp = (cid >> 24) & 0x01
        pf = (cid >> 16) & 0xFF
        ps = (cid >> 8) & 0xFF

        if pf < 240:
            return (dp << 16) | (pf << 8)
        return (dp << 16) | (pf << 8) | ps
    
    def _filter_log_ids_j1939(self, pgn: int) -> list[str]:
        out = []
        for s in self._all_log_ids():
            try:
                cid = int(s, 16)
            except ValueError:
                continue
            if self._extract_j1939_pgn(cid) == pgn:
                out.append(s)
        return sorted(out)

    def _filter_bam_sources(self, pgn: int) -> list[str]:
        if self.df is None or self.df.is_empty():
            return []
        sources = set()
        for raw_id, data_hex in self.df.select(["ID", "DATA"]).iter_rows():
            try:
                frame_id = can_id_to_int(raw_id)
            except ValueError:
                continue
            pf = (frame_id >> 16) & 0xFF
            if pf != 0xEC:
                continue
            payload = parse_hex_bytes(data_hex)
            if len(payload) < 8 or payload[0] != 0x20:
                continue
            msg_pgn = payload[5] | (payload[6] << 8) | (payload[7] << 16)
            if msg_pgn != pgn:
                continue
            sources.add(frame_id & 0xFF)
        return [f"{s:02X}" for s in sorted(sources)]

    def _payload_len(self) -> int:
        """Return max payload length (bytes) for the selected CAN ID/PGN in the log."""
        if self.df is None or self.df.is_empty() or "LEN" not in self.df.columns:
            return 8

        selected = self.id_box.currentText().strip() if hasattr(self, "id_box") else ""

        if self._selector_mode == "bam":
            pgn = self._parse_pgn_text(self.pgn_combo.currentText()) if hasattr(self, "pgn_combo") else None
            if pgn is None or not selected:
                return 8
            try:
                sa = int(selected, 16)
            except ValueError:
                return 8
            for raw_id, data_hex in self.df.select(["ID", "DATA"]).iter_rows():
                try:
                    frame_id = can_id_to_int(raw_id)
                except ValueError:
                    continue
                if (frame_id & 0xFF) != sa or (frame_id >> 16) & 0xFF != 0xEC:
                    continue
                try:
                    payload = parse_hex_bytes(data_hex)
                except Exception:
                    continue
                if len(payload) < 8 or payload[0] != 0x20:
                    continue
                if (payload[5] | (payload[6] << 8) | (payload[7] << 16)) != pgn:
                    continue
                total = payload[1] | (payload[2] << 8)
                return max(total, 1)
            return 8

        if not selected:
            return 8
        try:
            n = self.df.filter(pl.col("ID") == selected)["LEN"].max()
            return int(n) if n is not None else 8
        except Exception:
            return 8

    @staticmethod
    def _parse_pgn_text(text: str) -> int | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            return int(raw, 0)
        except ValueError:
            pass
        try:
            return int(raw, 16)
        except ValueError:
            return None

    def _build_dbc_group(self):
        box = QGroupBox(get_text("decode_dbc_group_title"))
        layout = QVBoxLayout(box)
        form = QFormLayout()

        self.dbc_status = QLabel(get_text("dbc_empty"))
        self.dbc_status.setStyleSheet(f"color: {get_active_theme().text_muted};")

        self.dbc_box = QComboBox()
        self.dbc_box.currentIndexChanged.connect(self._on_dbc_changed)

        self.message_box = QComboBox()
        self.message_box.currentIndexChanged.connect(self._on_message_changed)

        self.signal_box = QComboBox()

        self.param_box = QComboBox()
        self.param_box.addItems(get_option("decode_value_modes", []))

        form.addRow(self.dbc_status)
        form.addRow(get_text("dbc_label"), self.dbc_box)
        form.addRow(get_text("message_label"), self.message_box)
        form.addRow(get_text("signal_label"), self.signal_box)
        form.addRow(get_text("value_label"), self.param_box)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton(get_text("apply_dbc"))
        self.apply_btn.setAutoDefault(False)
        self.apply_btn.setDefault(False)
        self.apply_btn.clicked.connect(self._on_apply_dbc_clicked)

        self.show_all_btn = QPushButton(get_text("show_all_ids"))
        self.show_all_btn.setAutoDefault(False)
        self.show_all_btn.clicked.connect(self._on_show_all_ids_clicked)

        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.show_all_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        if self.dbc_manager:
            self.dbc_manager.entries_changed.connect(self._refresh_dbc_options)

        return box

    def _build_decode_group(self):
        box = QGroupBox(get_text("decode_group_title"))
        layout = QVBoxLayout(box)
        form = QFormLayout()

        self.name_edit = QLineEdit()

        self.match_mode = QComboBox()
        self.match_mode.addItems(get_option("signal_match_modes", []))
        self.match_mode.currentTextChanged.connect(self._on_match_mode_changed)

        self.pgn_combo = QComboBox()
        self.pgn_combo.setEditable(True)
        self.pgn_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.pgn_combo.currentTextChanged.connect(lambda _: self._refresh_id_box())

        self.id_box = QComboBox()
        self.id_box.addItems(self._all_log_ids())
        self.id_box.currentIndexChanged.connect(self._update_bit_matrix)
        self.id_label = QLabel(get_text("can_id_label"))

        self.start_bit = QSpinBox()
        self.start_bit.setRange(0, 63)
        self.start_bit.valueChanged.connect(self._update_bit_matrix)

        self.length = QSpinBox()
        self.length.setRange(1, 64)
        self.length.setValue(8)
        self.length.valueChanged.connect(self._on_length_changed)

        self.le = QRadioButton(get_text("little_endian"))
        self.be = QRadioButton(get_text("big_endian"))
        self.le.setChecked(True)
        self.le.toggled.connect(self._update_bit_matrix)

        endian_layout = QHBoxLayout()
        endian_layout.addWidget(self.le)
        endian_layout.addWidget(self.be)

        self.type_data = QComboBox()
        self.type_data.addItems(get_option("data_types", []))
        self.type_data.setCurrentText(get_option("default_data_type", "uint"))

        self.scale = _TrimmedDoubleSpinBox()
        self.scale.setDecimals(6)
        self.scale.setValue(1.0)
        self.scale.setMinimum(-1e9)
        self.scale.setMaximum(1e9)

        self.offset = _TrimmedDoubleSpinBox()
        self.offset.setDecimals(6)
        self.offset.setValue(0.0)
        self.offset.setMaximum(1e9)
        self.offset.setMinimum(-1e9)

        self.mux_start = QSpinBox()
        self.mux_start.setRange(0, 7)
        self.mux_start.valueChanged.connect(self._update_bit_matrix)

        self.mux_bytes = QSpinBox()
        self.mux_bytes.setRange(0, 8)
        self.mux_bytes.valueChanged.connect(self._on_mux_bytes_changed)

        self.mux_value = QLineEdit()
        self.mux_value.setEnabled(False)

        index = self.type_data.findText(get_option("float_data_type", "float32"))
        if index >= 0:
            self.type_data.model().item(index).setEnabled(self.length.value() == 32)

        form.addRow(get_text("signal_name_label"), self.name_edit)
        form.addRow(get_text("match_mode_label"), self.match_mode)
        form.addRow(get_text("pgn_label"), self.pgn_combo)
        form.addRow(self.id_label, self.id_box)
        form.addRow(get_text("start_bit_label"), self.start_bit)
        form.addRow(get_text("length_label"), self.length)
        form.addRow(get_text("endianness_label"), endian_layout)
        form.addRow(get_text("data_type_label"), self.type_data)
        form.addRow(get_text("scale_label"), self.scale)
        form.addRow(get_text("offset_label"), self.offset)
        self._pick_mux_btn = QToolButton()
        self._pick_mux_btn.setIcon(icon("crosshair"))
        self._pick_mux_btn.setCheckable(True)
        self._pick_mux_btn.setFixedSize(24, 24)
        self._pick_mux_btn.setToolTip("Click a matrix cell to set the MUX start byte")
        _t = get_active_theme()
        self._pick_mux_btn.setStyleSheet(
            f"QToolButton:checked {{ background-color: {_t.warn}; border: 1px solid {_t.border}; }}"
        )
        self._pick_mux_btn.toggled.connect(
            lambda on: self._set_pick_mode("mux_start" if on else None)
        )
        _ms_row = QHBoxLayout()
        _ms_row.setContentsMargins(0, 0, 0, 0)
        _ms_row.addWidget(self.mux_start)
        _ms_row.addWidget(self._pick_mux_btn)
        form.addRow(get_text("mux_start_label"), _ms_row)
        form.addRow(get_text("mux_bytes_label"), self.mux_bytes)
        form.addRow(get_text("mux_value_label"), self.mux_value)

        layout.addLayout(form)

        self._on_match_mode_changed(self.match_mode.currentText())

        return box

    def _on_match_mode_changed(self, mode: str):
        self._selector_mode = mode
        if mode == "bam":
            self.start_bit.setRange(0, 2047)
            self.length.setRange(1, 2048)
        else:
            self.start_bit.setRange(0, 63)
            self.length.setRange(1, 64)
        use_pgn = mode in ("j1939", "bam")
        self.pgn_combo.setEnabled(use_pgn)
        self.id_label.setText(get_text("source_label") if mode == "bam" else get_text("can_id_label"))
        if use_pgn:
            self._populate_pgn_combo(mode)
        self._refresh_id_box()

    def _populate_pgn_combo(self, mode: str) -> None:
        pgns = available_j1939_pgns(self.df) if mode == "j1939" else available_bam_pgns(self.df)
        prev = self.pgn_combo.currentText()
        self.pgn_combo.blockSignals(True)
        self.pgn_combo.clear()
        for pgn in pgns:
            self.pgn_combo.addItem(f"0x{pgn:04X}", pgn)
        self.pgn_combo.blockSignals(False)
        # pgn_combo is editable: setCurrentText on a missing value writes free-text and
        # silently breaks PGN filtering, so only restore if prev exists in the new list.
        valid = {self.pgn_combo.itemText(i) for i in range(self.pgn_combo.count())}
        if prev in valid:
            self.pgn_combo.setCurrentText(prev)

    def _refresh_id_box(self):
        prev = self.id_box.currentText().strip() or None
        ids: list[str] = []
        if self._selector_mode == "j1939":
            pgn = self._parse_pgn_text(self.pgn_combo.currentText())
            if pgn is not None:
                ids = self._filter_log_ids_j1939(pgn)
        elif self._selector_mode == "bam":
            pgn = self._parse_pgn_text(self.pgn_combo.currentText())
            if pgn is not None:
                ids = self._filter_bam_sources(pgn)
        else:
            ids = self._all_log_ids()

        self.id_box.blockSignals(True)
        self.id_box.clear()
        self.id_box.addItems(ids)
        self.id_box.blockSignals(False)

        if prev in ids:
            self.id_box.setCurrentText(prev)
        elif ids:
            self.id_box.setCurrentText(ids[0])

        # currentIndexChanged won't fire when index stays at 0 after repopulation,
        # so always refresh the matrix explicitly after rebuilding the ID list.
        self._update_bit_matrix()

    def _rebuild_matrix_grid(self, n_bytes: int) -> None:
        """Rebuild the bit matrix grid for the given payload size and attach to the scroll area."""
        self._matrix_n_bytes = n_bytes
        self.bit_labels: dict[tuple[int, int], QLabel] = {}

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(0)

        if n_bytes == 0:
            lbl = QLabel("No data — 0 bytes")
            lbl.setStyleSheet(f"color: {get_active_theme().text_muted};")
            outer.addWidget(lbl)
        else:
            grid_widget = QWidget()
            grid = QGridLayout(grid_widget)
            grid.setSpacing(1)
            grid.setContentsMargins(0, 0, 0, 0)

            for bit in range(7, -1, -1):
                hdr = QLabel(str(bit))
                hdr.setFixedSize(20, 20)
                hdr.setAlignment(Qt.AlignCenter)
                grid.addWidget(hdr, 0, 7 - bit + 1)

            for byte in range(n_bytes):
                row_lbl = QLabel(f"B{byte}")
                row_lbl.setFixedSize(28, 20)
                row_lbl.setAlignment(Qt.AlignCenter)
                grid.addWidget(row_lbl, byte + 1, 0)
                for bit in range(8):
                    lbl = QLabel(" ")
                    lbl.setFixedSize(20, 20)
                    lbl.setStyleSheet(f"border: 1px solid {get_active_theme().border};")
                    lbl.setAlignment(Qt.AlignCenter)
                    lbl.mousePressEvent = lambda _event, b=byte, c=bit: self._on_matrix_click(b, c)
                    cursor = Qt.CrossCursor if self._pick_mode == "mux_start" else Qt.PointingHandCursor
                    lbl.setCursor(cursor)
                    grid.addWidget(lbl, byte + 1, bit + 1)
                    self.bit_labels[(byte, bit)] = lbl

            outer.addWidget(grid_widget, 0, Qt.AlignTop | Qt.AlignLeft)

        outer.addStretch()
        self._matrix_scroll.setWidget(container)

    def _update_bit_matrix(self) -> None:
        n_bytes = self._payload_len()
        if n_bytes != self._matrix_n_bytes:
            self._rebuild_matrix_grid(n_bytes)

        if not self.bit_labels:
            return

        _t = get_active_theme()
        for lbl in self.bit_labels.values():
            lbl.setStyleSheet(f"border: 1px solid {_t.border};")

        mux_start = self.mux_start.value()
        mux_count = self.mux_bytes.value()
        for mux_byte in range(mux_start, min(n_bytes, mux_start + mux_count)):
            for bit in range(8):
                lbl = self.bit_labels.get((mux_byte, bit))
                if lbl:
                    lbl.setStyleSheet(f"background-color: {_t.warn}; border: 1px solid {_t.border};")

        start = self.start_bit.value()
        length = self.length.value()
        bits: list[int] = []

        if self.le.isChecked():
            byte = start // 8
            bit_in_byte = start % 8
            for _ in range(length):
                if byte >= n_bytes:
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
                if byte >= n_bytes:
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
                lbl.setStyleSheet(f"background-color: {_t.accent}; border: 1px solid {_t.border};")

    def _set_pick_mode(self, mode: str | None) -> None:
        self._pick_mode = mode
        if hasattr(self, "_pick_mux_btn") and mode != "mux_start":
            self._pick_mux_btn.blockSignals(True)
            self._pick_mux_btn.setChecked(False)
            self._pick_mux_btn.blockSignals(False)
        cursor = Qt.CrossCursor if mode == "mux_start" else Qt.PointingHandCursor
        for lbl in self.bit_labels.values():
            lbl.setCursor(cursor)

    def _on_matrix_click(self, byte: int, col_key: int) -> None:
        if self._pick_mode == "mux_start":
            self.mux_start.setValue(byte)
            self._set_pick_mode(None)
        else:
            self.start_bit.setValue(byte * 8 + (7 - col_key))

    def _on_length_changed(self, value: int):
        index = self.type_data.findText(get_option("float_data_type", "float32"))
        if index >= 0:
            self.type_data.model().item(index).setEnabled(value == 32)

        if value != 32 and self.type_data.currentText() == get_option("float_data_type", "float32"):
            self.type_data.setCurrentText(get_option("default_data_type", "uint"))

        self._update_bit_matrix()

    def _on_mux_bytes_changed(self, value: int):
        if value == 0:
            self.mux_value.setEnabled(False)
            self.mux_value.setText("")
        else:
            self.mux_value.setEnabled(True)
        self._update_bit_matrix()

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

        scaled = self.param_box.currentText() == get_option("decode_value_scaled", "Scaled")
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

            self.match_mode.setCurrentText(self._selector_mode)
            self.pgn_combo.setCurrentText("" if self._selector_pgn is None else f"0x{self._selector_pgn:04X}")
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
            self.mux_value.setText(self._format_mux_value(mux_value))
            self._update_bit_matrix()

            if self._selector_mode == "exact":
                valid_ids = self._filter_log_ids_exact(str(signal_data.get("can_id") or ""))
                self.id_box.blockSignals(True)
                self.id_box.clear()
                self.id_box.addItems(valid_ids)
                self.id_box.blockSignals(False)
                if valid_ids:
                    self.id_box.setCurrentText(valid_ids[0])
        finally:
            self._dbc_signal_guard = False

    def _on_show_all_ids_clicked(self):
        if self._selector_mode in ("j1939", "bam"):
            self._refresh_id_box()
            return

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
        pgn = self._parse_pgn_text(self.pgn_combo.currentText())

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
            "pgn": pgn,
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

        self.match_mode.setCurrentText(self._selector_mode)
        self.pgn_combo.setCurrentText("" if self._selector_pgn is None else f"0x{self._selector_pgn:04X}")

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
        self.mux_value.setText("" if signal.mux_bytes == 0 else self._format_mux_value(signal.mux_value))
        self.type_data.setCurrentText(signal.type_data)

        self._update_bit_matrix()

    @staticmethod
    def _format_mux_value(value) -> str:
        if value is None or value == "":
            return ""
        try:
            return hex(int(value))
        except (TypeError, ValueError):
            return str(value)
