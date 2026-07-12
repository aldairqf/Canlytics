from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from services.pgn_scanner import available_bam_pgns
from utils.can_id import can_id_to_int
from utils.j1939 import J1939

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_KINDS: list[tuple[str, str]] = [
    ("Signal (decoded)", "signal"),
    ("Raw CAN field",    "raw_field"),
]

_COMBINE_OPS: list[tuple[str, str]] = [
    ("previous - current",      "sub"),
    ("previous + current",      "add"),
    ("previous * current",      "mul"),
    ("previous / current",      "div"),
    ("max(previous, current)",  "max"),
    ("min(previous, current)",  "min"),
]

_TRANSFORM_OPS: list[tuple[str, str]] = [
    ("Scale  ×  constant",    "scale"),
    ("Offset +  constant",    "offset"),
    ("Absolute value  |y|",   "abs"),
    ("Clamp to range",        "clamp"),
    ("Conditional transform", "conditional"),
    ("Math function",         "math"),
    ("Round to N decimals",   "round"),
]

_MATH_FNS: list[tuple[str, str]] = [
    ("√  sqrt",           "sqrt"),
    ("|·|  abs",          "abs"),
    ("log₁₀",             "log10"),
    ("ln  (natural log)", "ln"),
    ("eˣ  exp",           "exp"),
    ("sin",               "sin"),
    ("cos",               "cos"),
    ("tan",               "tan"),
]

_CMP_OPS: list[str] = [">", "<", ">=", "<=", "==", "!="]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_int(text: str, default: int = 0) -> int:
    text = text.strip()
    if not text:
        return default
    try:
        return int(text, 0)
    except ValueError:
        return default


def _all_log_ids(df) -> list[str]:
    if df is None or df.is_empty() or "ID" not in df.columns:
        return []
    return sorted(str(item) for item in df["ID"].unique().to_list())


def _branch_label(index: int) -> str:
    if 0 <= index < 26:
        return chr(ord("A") + index)
    return f"S{index + 1}"


def _combo_int(combo: QComboBox, default: int = 0) -> int:
    data = combo.currentData()
    if data is not None:
        try:
            return int(data)
        except (TypeError, ValueError):
            pass
    return _parse_int(combo.currentText(), default)


def _set_combo_int(combo: QComboBox, value: int, label_fn=str) -> None:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    for i in range(combo.count()):
        data = combo.itemData(i)
        if data is not None and int(data) == value:
            combo.setCurrentIndex(i)
            return
    combo.addItem(label_fn(value), value)
    combo.setCurrentIndex(combo.count() - 1)


def _spin(lo: float = -1e9, hi: float = 1e9, val: float = 0.0,
          dec: int = 6, w: int = 90) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setDecimals(dec)
    s.setFixedWidth(w)
    return s


# ---------------------------------------------------------------------------
# _SourceRow
# ---------------------------------------------------------------------------

class _SourceRow(QWidget):
    changed = Signal()
    remove_requested = Signal(object)

    def __init__(
        self,
        available_signals: list[str],
        can_ids: list[str],
        bam_pgns: list[int],
        removable: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._build_ui(available_signals, can_ids, bam_pgns, removable)

    # ------------------------------------------------------------------ #
    # Build                                                                #
    # ------------------------------------------------------------------ #

    def _build_ui(
        self,
        available_signals: list[str],
        can_ids: list[str],
        bam_pgns: list[int],
        removable: bool,
    ):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        self._kind_combo = QComboBox()
        self._kind_combo.setMinimumWidth(180)
        for label, val in _SOURCE_KINDS:
            self._kind_combo.addItem(label, val)
        layout.addWidget(self._kind_combo)

        self._stack = QStackedWidget()

        # -- page 0: signal -----------------------------------------------
        p0 = QWidget()
        l0 = QHBoxLayout(p0)
        l0.setContentsMargins(0, 0, 0, 0)
        self._sig_combo = QComboBox()
        self._sig_combo.setMinimumWidth(160)
        self._sig_combo.addItems(available_signals)
        l0.addWidget(self._sig_combo)
        l0.addStretch()
        self._stack.addWidget(p0)

        # -- page 1: raw_field --------------------------------------------
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 2, 0, 2)
        l1.setSpacing(4)

        # row 1: frame / BAM selector
        row1 = QWidget()
        rl1 = QHBoxLayout(row1)
        rl1.setContentsMargins(0, 0, 0, 0)
        rl1.setSpacing(6)

        self._raw_bam = QCheckBox("BAM")
        rl1.addWidget(self._raw_bam)

        self._raw_id_stack = QStackedWidget()

        # id_stack page 0: raw CAN frame
        fp = QWidget()
        fl = QHBoxLayout(fp)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(4)
        fl.addWidget(QLabel("CAN ID:"))
        self._raw_id = QComboBox()
        self._raw_id.setFixedWidth(110)
        for cid in can_ids:
            try:
                self._raw_id.addItem(cid, can_id_to_int(cid))
            except ValueError:
                continue
        fl.addWidget(self._raw_id)
        fl.addWidget(QLabel("Mode:"))
        self._raw_mode = QComboBox()
        self._raw_mode.addItems(["exact", "j1939"])
        fl.addWidget(self._raw_mode)
        fl.addStretch()
        self._raw_id_stack.addWidget(fp)

        # id_stack page 1: BAM
        bp = QWidget()
        bl = QHBoxLayout(bp)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        bl.addWidget(QLabel("PGN:"))
        self._raw_pgn = QComboBox()
        self._raw_pgn.setFixedWidth(100)
        for pgn in bam_pgns:
            self._raw_pgn.addItem(J1939.format_pgn(pgn), int(pgn))
        bl.addWidget(self._raw_pgn)
        bl.addStretch()
        self._raw_id_stack.addWidget(bp)

        rl1.addWidget(self._raw_id_stack)
        l1.addWidget(row1)

        # row 2: bit params + data type
        row2 = QWidget()
        rl2 = QHBoxLayout(row2)
        rl2.setContentsMargins(0, 0, 0, 0)
        rl2.setSpacing(4)
        rl2.addWidget(QLabel("Start bit:"))
        self._raw_start_bit = QSpinBox()
        self._raw_start_bit.setRange(0, 65535)
        self._raw_start_bit.setFixedWidth(70)
        rl2.addWidget(self._raw_start_bit)
        rl2.addWidget(QLabel("Length (bits):"))
        self._raw_length = QSpinBox()
        self._raw_length.setRange(1, 65536)
        self._raw_length.setValue(8)
        self._raw_length.setFixedWidth(70)
        rl2.addWidget(self._raw_length)
        rl2.addWidget(QLabel("Byte order:"))
        self._raw_byte_order = QComboBox()
        self._raw_byte_order.addItem("LE  (Intel)", "LE")
        self._raw_byte_order.addItem("BE  (Motorola)", "BE")
        self._raw_byte_order.setFixedWidth(120)
        rl2.addWidget(self._raw_byte_order)
        rl2.addWidget(QLabel("Type:"))
        self._raw_type = QComboBox()
        self._raw_type.addItem("Unsigned", "uint")
        self._raw_type.addItem("Signed", "int")
        self._raw_type.addItem("Float 32", "float32")
        self._raw_type.setFixedWidth(90)
        rl2.addWidget(self._raw_type)
        rl2.addStretch()
        l1.addWidget(row2)

        # row 3: MUX (optional)
        row3 = QWidget()
        rl3 = QHBoxLayout(row3)
        rl3.setContentsMargins(0, 0, 0, 0)
        rl3.setSpacing(4)
        self._raw_mux_check = QCheckBox("MUX")
        rl3.addWidget(self._raw_mux_check)
        self._raw_mux_widget = QWidget()
        mux_l = QHBoxLayout(self._raw_mux_widget)
        mux_l.setContentsMargins(0, 0, 0, 0)
        mux_l.setSpacing(4)
        mux_l.addWidget(QLabel("Start byte:"))
        self._raw_mux_start = QSpinBox()
        self._raw_mux_start.setRange(0, 65535)
        self._raw_mux_start.setFixedWidth(70)
        mux_l.addWidget(self._raw_mux_start)
        mux_l.addWidget(QLabel("Len (bytes):"))
        self._raw_mux_bytes = QSpinBox()
        self._raw_mux_bytes.setRange(1, 8)
        self._raw_mux_bytes.setFixedWidth(50)
        mux_l.addWidget(self._raw_mux_bytes)
        mux_l.addWidget(QLabel("Value:"))
        self._raw_mux_value = QSpinBox()
        self._raw_mux_value.setRange(0, 65535)
        self._raw_mux_value.setFixedWidth(70)
        mux_l.addWidget(self._raw_mux_value)
        rl3.addWidget(self._raw_mux_widget)
        rl3.addStretch()
        self._raw_mux_widget.setVisible(False)
        l1.addWidget(row3)

        self._stack.addWidget(p1)

        layout.addWidget(self._stack, 1)

        if removable:
            rm_btn = QPushButton("×")
            rm_btn.setFixedWidth(26)
            rm_btn.setToolTip("Remove this source")
            rm_btn.clicked.connect(lambda: self.remove_requested.emit(self))
            layout.addWidget(rm_btn)

        # Connections
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self._raw_bam.toggled.connect(
            lambda checked: self._raw_id_stack.setCurrentIndex(1 if checked else 0)
        )
        self._raw_mux_check.toggled.connect(self._raw_mux_widget.setVisible)

        for w in (self._sig_combo, self._raw_id, self._raw_mode, self._raw_pgn,
                  self._raw_byte_order, self._raw_type):
            w.currentIndexChanged.connect(self.changed)
        for w in (self._raw_start_bit, self._raw_length,
                  self._raw_mux_start, self._raw_mux_bytes, self._raw_mux_value):
            w.valueChanged.connect(self.changed)
        for w in (self._raw_bam, self._raw_mux_check):
            w.toggled.connect(self.changed)

    # ------------------------------------------------------------------ #
    # Slots                                                                #
    # ------------------------------------------------------------------ #

    def _on_kind_changed(self, idx: int):
        self._stack.setCurrentIndex(idx)
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_config(self) -> dict:
        kind: str = self._kind_combo.currentData()
        if kind == "signal":
            return {"kind": "signal", "signal_name": self._sig_combo.currentText()}
        # raw_field
        bam = self._raw_bam.isChecked()
        cfg: dict = {
            "kind": "raw_field",
            "bam": bam,
            "start_bit": self._raw_start_bit.value(),
            "length": self._raw_length.value(),
            "byte_order": self._raw_byte_order.currentData(),
            "type_data": self._raw_type.currentData(),
        }
        if bam:
            cfg["pgn"] = _combo_int(self._raw_pgn)
        else:
            cfg["can_id"] = _combo_int(self._raw_id)
            cfg["mode"] = self._raw_mode.currentText()
        if self._raw_mux_check.isChecked():
            cfg["mux_start"] = self._raw_mux_start.value()
            cfg["mux_bytes"] = self._raw_mux_bytes.value()
            cfg["mux_value"] = self._raw_mux_value.value()
        return cfg

    def load_config(self, config: dict):
        kind = config.get("kind", "signal")

        # Backward compat: map old kinds to raw_field
        if kind == "bam_extract":
            config = {
                "kind": "raw_field",
                "bam": True,
                "pgn": config.get("pgn", 0),
                "start_bit": config.get("start_bit", 0),
                "length": config.get("length", 8),
                "byte_order": config.get("byte_order", "LE"),
                "type_data": "uint",
            }
            kind = "raw_field"
        elif kind == "raw_extract":
            config = {
                "kind": "raw_field",
                "bam": False,
                "can_id": config.get("can_id", 0),
                "mode": config.get("mode", "exact"),
                "start_bit": config.get("start_bit", 0),
                "length": config.get("length", 8),
                "byte_order": config.get("byte_order", "LE"),
                "type_data": "uint",
            }
            kind = "raw_field"

        idx = next((i for i, (_, v) in enumerate(_SOURCE_KINDS) if v == kind), 0)
        self._kind_combo.blockSignals(True)
        self._kind_combo.setCurrentIndex(idx)
        self._kind_combo.blockSignals(False)
        self._stack.setCurrentIndex(idx)

        if kind == "signal":
            i = self._sig_combo.findText(config.get("signal_name", ""))
            if i >= 0:
                self._sig_combo.setCurrentIndex(i)
        elif kind == "raw_field":
            bam = config.get("bam", False)
            self._raw_bam.blockSignals(True)
            self._raw_bam.setChecked(bam)
            self._raw_bam.blockSignals(False)
            self._raw_id_stack.setCurrentIndex(1 if bam else 0)

            if bam:
                _set_combo_int(self._raw_pgn, config.get("pgn", 0), J1939.format_pgn)
            else:
                _set_combo_int(self._raw_id, config.get("can_id", 0),
                               lambda v: f"{int(v):X}")
                i = self._raw_mode.findText(config.get("mode", "exact"))
                if i >= 0:
                    self._raw_mode.setCurrentIndex(i)

            self._raw_start_bit.setValue(config.get("start_bit", 0))
            self._raw_length.setValue(config.get("length", 8))
            i = self._raw_byte_order.findData(config.get("byte_order", "LE"))
            if i >= 0:
                self._raw_byte_order.setCurrentIndex(i)
            i = self._raw_type.findData(config.get("type_data", "uint"))
            if i >= 0:
                self._raw_type.setCurrentIndex(i)

            mux_start = config.get("mux_start")
            has_mux = mux_start is not None
            self._raw_mux_check.blockSignals(True)
            self._raw_mux_check.setChecked(has_mux)
            self._raw_mux_check.blockSignals(False)
            self._raw_mux_widget.setVisible(has_mux)
            if has_mux:
                self._raw_mux_start.setValue(int(mux_start))
                self._raw_mux_bytes.setValue(config.get("mux_bytes", 1))
                self._raw_mux_value.setValue(config.get("mux_value", 0))

    def set_available_signals(self, names: list[str]):
        current = self._sig_combo.currentText()
        self._sig_combo.blockSignals(True)
        self._sig_combo.clear()
        self._sig_combo.addItems(names)
        i = self._sig_combo.findText(current)
        if i >= 0:
            self._sig_combo.setCurrentIndex(i)
        self._sig_combo.blockSignals(False)

    def set_available_frames(self, can_ids: list[str], bam_pgns: list[int]):
        current_id = self._raw_id.currentData()
        self._raw_id.blockSignals(True)
        self._raw_id.clear()
        for can_id in can_ids:
            try:
                self._raw_id.addItem(can_id, can_id_to_int(can_id))
            except ValueError:
                continue
        if current_id is not None:
            _set_combo_int(self._raw_id, int(current_id), lambda v: f"{int(v):X}")
        self._raw_id.blockSignals(False)

        current_pgn = self._raw_pgn.currentData()
        self._raw_pgn.blockSignals(True)
        self._raw_pgn.clear()
        for pgn in bam_pgns:
            self._raw_pgn.addItem(J1939.format_pgn(pgn), int(pgn))
        if current_pgn is not None:
            _set_combo_int(self._raw_pgn, int(current_pgn), J1939.format_pgn)
        self._raw_pgn.blockSignals(False)


# ---------------------------------------------------------------------------
# _TransformRow
# ---------------------------------------------------------------------------

class _TransformRow(QWidget):
    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, op: str = "scale", parent: QWidget | None = None):
        super().__init__(parent)
        self._build_ui()
        idx = next((i for i, (_, v) in enumerate(_TRANSFORM_OPS) if v == op), 0)
        self._op_combo.blockSignals(True)
        self._op_combo.setCurrentIndex(idx)
        self._op_combo.blockSignals(False)
        self._stack.setCurrentIndex(idx)

    # ------------------------------------------------------------------ #
    # Build                                                                #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        self._op_combo = QComboBox()
        self._op_combo.setMinimumWidth(190)
        for label, val in _TRANSFORM_OPS:
            self._op_combo.addItem(label, val)
        layout.addWidget(self._op_combo)

        self._stack = QStackedWidget()

        # -- page 0: scale ------------------------------------------------
        p_sc = QWidget()
        l_sc = QHBoxLayout(p_sc); l_sc.setContentsMargins(0, 0, 0, 0)
        l_sc.addWidget(QLabel("×"))
        self._scale_val = _spin(val=1.0)
        l_sc.addWidget(self._scale_val); l_sc.addStretch()
        self._stack.addWidget(p_sc)

        # -- page 1: offset -----------------------------------------------
        p_of = QWidget()
        l_of = QHBoxLayout(p_of); l_of.setContentsMargins(0, 0, 0, 0)
        l_of.addWidget(QLabel("+"))
        self._offset_val = _spin()
        l_of.addWidget(self._offset_val); l_of.addStretch()
        self._stack.addWidget(p_of)

        # -- page 2: abs --------------------------------------------------
        p_ab = QWidget()
        l_ab = QHBoxLayout(p_ab); l_ab.setContentsMargins(0, 0, 0, 0)
        l_ab.addWidget(QLabel("(no parameters)")); l_ab.addStretch()
        self._stack.addWidget(p_ab)

        # -- page 3: clamp ------------------------------------------------
        p_cl = QWidget()
        l_cl = QHBoxLayout(p_cl); l_cl.setContentsMargins(0, 0, 0, 0)
        l_cl.addWidget(QLabel("min:"))
        self._clamp_min = _spin()
        l_cl.addWidget(self._clamp_min)
        l_cl.addWidget(QLabel("max:"))
        self._clamp_max = _spin(val=100.0)
        l_cl.addWidget(self._clamp_max); l_cl.addStretch()
        self._stack.addWidget(p_cl)

        # -- page 4: conditional ------------------------------------------
        p_cn = QWidget()
        l_cn = QHBoxLayout(p_cn); l_cn.setContentsMargins(0, 0, 0, 0)
        l_cn.addWidget(QLabel("if y"))
        self._cond_cmp = QComboBox(); self._cond_cmp.addItems(_CMP_OPS)
        self._cond_cmp.setFixedWidth(50)
        l_cn.addWidget(self._cond_cmp)
        self._cond_thresh = _spin(w=80)
        l_cn.addWidget(self._cond_thresh)
        l_cn.addWidget(QLabel("→ ×"))
        self._cond_ts = _spin(val=1.0, w=75)
        l_cn.addWidget(self._cond_ts)
        l_cn.addWidget(QLabel("+"))
        self._cond_to = _spin(w=75)
        l_cn.addWidget(self._cond_to)
        l_cn.addWidget(QLabel("else ×"))
        self._cond_fs = _spin(val=1.0, w=75)
        l_cn.addWidget(self._cond_fs)
        l_cn.addWidget(QLabel("+"))
        self._cond_fo = _spin(w=75)
        l_cn.addWidget(self._cond_fo)
        l_cn.addStretch()
        self._stack.addWidget(p_cn)

        # -- page 5: math -------------------------------------------------
        p_ma = QWidget()
        l_ma = QHBoxLayout(p_ma); l_ma.setContentsMargins(0, 0, 0, 0)
        l_ma.addWidget(QLabel("fn:"))
        self._math_fn = QComboBox()
        for label, val in _MATH_FNS:
            self._math_fn.addItem(label, val)
        l_ma.addWidget(self._math_fn); l_ma.addStretch()
        self._stack.addWidget(p_ma)

        # -- page 6: round ------------------------------------------------
        p_ro = QWidget()
        l_ro = QHBoxLayout(p_ro); l_ro.setContentsMargins(0, 0, 0, 0)
        l_ro.addWidget(QLabel("decimals:"))
        self._round_dec = QSpinBox()
        self._round_dec.setRange(0, 12); self._round_dec.setValue(2)
        self._round_dec.setFixedWidth(60)
        l_ro.addWidget(self._round_dec); l_ro.addStretch()
        self._stack.addWidget(p_ro)

        layout.addWidget(self._stack, 1)

        rm_btn = QPushButton("×")
        rm_btn.setFixedWidth(26)
        rm_btn.setToolTip("Remove this transform")
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(rm_btn)

        # Connections
        self._op_combo.currentIndexChanged.connect(self._on_op_changed)
        for w in (self._scale_val, self._offset_val,
                  self._clamp_min, self._clamp_max,
                  self._cond_thresh, self._cond_ts, self._cond_to,
                  self._cond_fs, self._cond_fo):
            w.valueChanged.connect(self.changed)
        for w in (self._cond_cmp, self._math_fn):
            w.currentIndexChanged.connect(self.changed)
        self._round_dec.valueChanged.connect(self.changed)

    # ------------------------------------------------------------------ #
    # Slots                                                                #
    # ------------------------------------------------------------------ #

    def _on_op_changed(self, idx: int):
        self._stack.setCurrentIndex(idx)
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_config(self) -> dict:
        op: str = self._op_combo.currentData()
        if op == "scale":
            return {"op": "scale", "value": self._scale_val.value()}
        if op == "offset":
            return {"op": "offset", "value": self._offset_val.value()}
        if op == "abs":
            return {"op": "abs"}
        if op == "clamp":
            return {"op": "clamp",
                    "min": self._clamp_min.value(),
                    "max": self._clamp_max.value()}
        if op == "conditional":
            return {
                "op": "conditional",
                "cmp": self._cond_cmp.currentText(),
                "threshold": self._cond_thresh.value(),
                "true_scale": self._cond_ts.value(),
                "true_offset": self._cond_to.value(),
                "false_scale": self._cond_fs.value(),
                "false_offset": self._cond_fo.value(),
            }
        if op == "math":
            return {"op": "math", "fn": self._math_fn.currentData()}
        # round
        return {"op": "round", "decimals": self._round_dec.value()}

    def load_config(self, config: dict):
        op = config.get("op", "scale")
        idx = next((i for i, (_, v) in enumerate(_TRANSFORM_OPS) if v == op), 0)
        self._op_combo.blockSignals(True)
        self._op_combo.setCurrentIndex(idx)
        self._op_combo.blockSignals(False)
        self._stack.setCurrentIndex(idx)

        if op == "scale":
            self._scale_val.setValue(config.get("value", 1.0))
        elif op == "offset":
            self._offset_val.setValue(config.get("value", 0.0))
        elif op == "clamp":
            self._clamp_min.setValue(config.get("min", 0.0))
            self._clamp_max.setValue(config.get("max", 100.0))
        elif op == "conditional":
            i = self._cond_cmp.findText(config.get("cmp", ">"))
            if i >= 0:
                self._cond_cmp.setCurrentIndex(i)
            self._cond_thresh.setValue(config.get("threshold", 0.0))
            self._cond_ts.setValue(config.get("true_scale", 1.0))
            self._cond_to.setValue(config.get("true_offset", 0.0))
            self._cond_fs.setValue(config.get("false_scale", 1.0))
            self._cond_fo.setValue(config.get("false_offset", 0.0))
        elif op == "math":
            for i, (_, v) in enumerate(_MATH_FNS):
                if v == config.get("fn", "sqrt"):
                    self._math_fn.setCurrentIndex(i)
                    break
        elif op == "round":
            self._round_dec.setValue(config.get("decimals", 2))


# ---------------------------------------------------------------------------
# _TransformList
# ---------------------------------------------------------------------------

class _TransformList(QWidget):
    changed = Signal()

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[_TransformRow] = []
        self._build_ui(title)

    def _build_ui(self, title: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._box = QGroupBox(title)
        self._layout = QVBoxLayout(self._box)
        self._layout.setSpacing(4)

        self._add_combo = QComboBox()
        self._add_combo.addItem("+ Add function...")
        for label, val in _TRANSFORM_OPS:
            self._add_combo.addItem(label, val)
        self._add_combo.currentIndexChanged.connect(self._on_add_transform)
        self._layout.addWidget(self._add_combo)

        root.addWidget(self._box)

    def _on_add_transform(self, idx: int):
        if idx == 0:
            return
        _, op = _TRANSFORM_OPS[idx - 1]
        self._add_row({"op": op})
        self._add_combo.blockSignals(True)
        self._add_combo.setCurrentIndex(0)
        self._add_combo.blockSignals(False)
        self.changed.emit()

    def _add_row(self, config: dict):
        row = _TransformRow(op=config.get("op", "scale"))
        row.load_config(config)
        row.changed.connect(self.changed)
        row.remove_requested.connect(self._on_remove_transform)
        self._rows.append(row)
        combo_idx = self._layout.indexOf(self._add_combo)
        self._layout.insertWidget(combo_idx, row)

    def _on_remove_transform(self, row: _TransformRow):
        if row in self._rows:
            self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self.changed.emit()

    def get_config(self) -> list[dict]:
        return [row.get_config() for row in self._rows]

    def load_config(self, transforms: list[dict]):
        for row in list(self._rows):
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        for transform in transforms or []:
            self._add_row(transform)

    def set_title(self, title: str):
        self._box.setTitle(title)


# ---------------------------------------------------------------------------
# _BranchWidget
# ---------------------------------------------------------------------------

class _BranchWidget(QWidget):
    changed = Signal()
    remove_requested = Signal(object)

    def __init__(
        self,
        label: str,
        available_signals: list[str],
        can_ids: list[str],
        bam_pgns: list[int],
        *,
        removable: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._label = label
        self._build_ui(label, available_signals, can_ids, bam_pgns, removable)

    def _build_ui(
        self,
        label: str,
        available_signals: list[str],
        can_ids: list[str],
        bam_pgns: list[int],
        removable: bool,
    ):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._box = QGroupBox(f"Signal {label}")
        box_layout = QVBoxLayout(self._box)
        box_layout.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("Source:"))
        header.addStretch()
        if removable:
            remove_btn = QPushButton("Remove signal")
            remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
            header.addWidget(remove_btn)
        box_layout.addLayout(header)

        self._source = _SourceRow(available_signals, can_ids, bam_pgns)
        self._source.changed.connect(self.changed)
        box_layout.addWidget(self._source)

        self._transforms = _TransformList(f"Functions for Signal {label}")
        self._transforms.changed.connect(self.changed)
        box_layout.addWidget(self._transforms)

        root.addWidget(self._box)

    def get_config(self) -> dict:
        return {
            "label": self._label,
            "source": self._source.get_config(),
            "transforms": self._transforms.get_config(),
        }

    def load_config(self, config: dict):
        self._source.load_config(config.get("source", {}))
        self._transforms.load_config(list(config.get("transforms") or []))

    def set_available_signals(self, names: list[str]):
        self._source.set_available_signals(names)

    def set_available_frames(self, can_ids: list[str], bam_pgns: list[int]):
        self._source.set_available_frames(can_ids, bam_pgns)

    def set_label(self, label: str):
        self._label = label
        self._box.setTitle(f"Signal {label}")
        self._transforms.set_title(f"Functions for Signal {label}")


# ---------------------------------------------------------------------------
# PipelineBuilder
# ---------------------------------------------------------------------------

class PipelineBuilder(QWidget):
    """Visual derived-signal pipeline builder."""

    changed = Signal()

    def __init__(
        self,
        available_signals: list[str] | None = None,
        df=None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._available_signals: list[str] = list(available_signals or [])
        self._can_ids: list[str] = _all_log_ids(df)
        self._bam_pgns: list[int] = available_bam_pgns(df) if df is not None else []
        self._branches: list[_BranchWidget] = []
        self._combine_rows: list[QWidget] = []
        self._combine_labels: list[QLabel] = []
        self._combine_combos: list[QComboBox] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(8)

        self._branch_layout = QVBoxLayout()
        self._branch_layout.setSpacing(8)
        root.addLayout(self._branch_layout)

        self._branch_a = self._create_branch("A", removable=False)
        self._branches.append(self._branch_a)
        self._branch_layout.addWidget(self._branch_a)

        self._add_branch_btn = QPushButton("+ Add Signal B")
        self._add_branch_btn.clicked.connect(self._on_add_branch)
        self._branch_layout.addWidget(self._add_branch_btn)

        self._output_transforms = _TransformList("Functions for final result")
        self._output_transforms.changed.connect(self._on_changed)
        root.addWidget(self._output_transforms)
        root.addStretch()

    def _create_branch(self, label: str, *, removable: bool) -> _BranchWidget:
        branch = _BranchWidget(
            label,
            self._available_signals,
            self._can_ids,
            self._bam_pgns,
            removable=removable,
        )
        branch.changed.connect(self._on_changed)
        branch.remove_requested.connect(self._on_remove_branch)
        return branch

    def _on_add_branch(self):
        label = _branch_label(len(self._branches))
        row, label_widget, combo = self._create_combine_row(len(self._branches) - 1)
        branch = self._create_branch(label, removable=True)
        self._combine_rows.append(row)
        self._combine_labels.append(label_widget)
        self._combine_combos.append(combo)
        self._branches.append(branch)
        button_idx = self._branch_layout.indexOf(self._add_branch_btn)
        self._branch_layout.insertWidget(button_idx, row)
        self._branch_layout.insertWidget(button_idx + 1, branch)
        self._refresh_branch_labels()
        self._refresh_add_button()
        self._on_changed()

    def _on_remove_branch(self, branch: _BranchWidget):
        if branch not in self._branches or branch is self._branch_a:
            return
        idx = self._branches.index(branch)
        self._branches.remove(branch)
        branch.setParent(None)
        branch.deleteLater()
        row_idx = idx - 1
        if 0 <= row_idx < len(self._combine_rows):
            row = self._combine_rows.pop(row_idx)
            self._combine_labels.pop(row_idx)
            self._combine_combos.pop(row_idx)
            row.setParent(None)
            row.deleteLater()
        self._refresh_branch_labels()
        self._refresh_add_button()
        self._on_changed()

    def _create_combine_row(self, index: int) -> tuple[QWidget, QLabel, QComboBox]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel()
        layout.addWidget(label)
        combo = QComboBox()
        for text, val in _COMBINE_OPS:
            combo.addItem(text, val)
        combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(combo)
        layout.addStretch()
        self._set_combine_label(label, index)
        return row, label, combo

    def _refresh_branch_labels(self):
        for idx, branch in enumerate(self._branches):
            branch.set_label(_branch_label(idx))
        for idx, label in enumerate(self._combine_labels):
            self._set_combine_label(label, idx)

    def _set_combine_label(self, label: QLabel, index: int):
        label.setText(f"Operation {_branch_label(index)} -> {_branch_label(index + 1)}:")

    def _refresh_add_button(self):
        self._add_branch_btn.setText(f"+ Add Signal {_branch_label(len(self._branches))}")

    def _on_changed(self):
        self.changed.emit()

    def get_config(self) -> dict:
        branches = [branch.get_config() for branch in self._branches]
        ops = [{"op": combo.currentData()} for combo in self._combine_combos]
        return {
            "type": "pipeline",
            "version": 3,
            "branches": branches,
            "combine": {"ops": ops} if ops else None,
            "output_transforms": self._output_transforms.get_config(),
        }

    def load_config(self, config: dict):
        branches = config.get("branches") or []
        if branches:
            self._branch_a.load_config(branches[0])
        while len(self._branches) < len(branches):
            self._on_add_branch()
        while len(self._branches) > max(1, len(branches)):
            self._on_remove_branch(self._branches[-1])
        for idx, branch_config in enumerate(branches[1:], start=1):
            if idx < len(self._branches):
                self._branches[idx].load_config(branch_config)

        combine = config.get("combine") or {}
        ops = combine.get("ops") or []
        for combo, op_config in zip(self._combine_combos, ops):
            combine_kind = op_config.get("op")
            for i, (_, val) in enumerate(_COMBINE_OPS):
                if val == combine_kind:
                    combo.setCurrentIndex(i)
                    break
        self._output_transforms.load_config(list(config.get("output_transforms") or []))
        self._on_changed()

    def set_available_signals(self, names: list[str]):
        self._available_signals = list(names)
        for branch in self._branches:
            branch.set_available_signals(names)

    def set_dataframe(self, df):
        self._can_ids = _all_log_ids(df)
        self._bam_pgns = available_bam_pgns(df) if df is not None else []
        for branch in self._branches:
            branch.set_available_frames(self._can_ids, self._bam_pgns)
