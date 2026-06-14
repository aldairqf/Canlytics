from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from models.derived_signal import DerivedSignal
from models.derived_view_signal import DerivedViewSignal
from services.formula_context import build_formula_context
from services.formula_evaluator import FormulaError, evaluate
from views.signal.tabs.filter_tab import FilterTab
from views.signal.tabs.style_tab import StyleTab

# ------------------------------------------------------------------ #
# Formula reference — shown as a read-only help panel                  #
# ------------------------------------------------------------------ #

_REFERENCE = """\
── Available helpers ─────────────────────────────────────────────────────────

np          NumPy module  (np.where, np.array, np.abs, …)
math        Python math   (math.pi, math.log, …)

signal(name)
    → (ts, y)  Already-decoded signal from this plot.
    Example: ts, y = signal('engine_rpm')

bam_messages(pgn, source=None)
    → list[BamMessage]  Reassembled J1939 BAM packets.
    Attributes: .timestamp (float), .data (bytes)
    Example:
        for msg in bam_messages(0xFF17):
            val = decode_bytes(msg.data, 18, 2, 'int16le')

bam_extract(pgn, offset, n, dtype, source=None)
    → (ts, y)  Shortcut: extract one field from all BAM packets.
    Example: ts, y = bam_extract(0xFF17, 18, 2, 'int16le')

raw_frames(can_id, mode='exact', pgn=None)
    → iterator of (ts, bytes)  Raw CAN frame payloads.
    Example:
        for ts_f, payload in raw_frames(0x18FF0001):
            ...

raw_extract(can_id, offset, n, dtype, mode='exact', pgn=None)
    → (ts, y)  Extract one field from raw CAN frames.
    Example: ts, y = raw_extract(0x18FF0001, 2, 2, 'uint16le')

decode_bytes(data, offset, n, dtype)
    → scalar  Decode bytes from a bytes object.
    dtypes: uint8, int8, uint16le, int16le, uint16be, int16be,
            uint32le, int32le, uint32be, int32be,
            float32le, float32be, float64le, float64be
    Example: decode_bytes(payload, 18, 2, 'int16le')

align(*[(ts1, y1), (ts2, y2), …])
    → (common_ts, [y1_aligned, y2_aligned, …])
    Forward-fills each series onto the union timestamp axis.
    Example:
        ts_a, a = signal('speed')
        ts_b, b = bam_extract(0xFF17, 0, 2, 'uint16le')
        ts, (sa, sb) = align((ts_a, a), (ts_b, b))

── result contract ───────────────────────────────────────────────────────────

Your formula MUST assign:
    result = (ts_array, y_array)   ← explicit timestamps
    result = y_array               ← values only (no timestamps)

── examples ──────────────────────────────────────────────────────────────────

# Scale a decoded signal
ts, y = signal('engine_rpm')
result = ts, y / 60.0

# Conditional transform
ts, y = signal('temperature')
result = ts, np.where(y > 180, y * 2 - 50, y)

# Combine two signals
ts_a, a = signal('pressure_hi')
ts_b, b = signal('pressure_lo')
ts, (pa, pb) = align((ts_a, a), (ts_b, b))
result = ts, pa - pb

# BAM extraction (RSSI at bytes 18-19 of PGN 0xFF17 packets)
messages = bam_messages(pgn=0xFF17)
ts_out, val_out = [], []
for msg in messages:
    for i in range(0, len(msg.data), 20):
        chunk = msg.data[i : i + 20]
        if len(chunk) == 20:
            ts_out.append(msg.timestamp)
            val_out.append(decode_bytes(chunk, 18, 2, 'int16le'))
result = np.array(ts_out), np.array(val_out)

# Raw CAN bytes
ts, y = raw_extract(0x18FF0001, offset=2, n=2, dtype='uint16le')
result = ts, y * 0.1
"""


class DerivedSignalDialog(QDialog):
    def __init__(
        self,
        vm,
        dvs: DerivedViewSignal | None = None,
        parent=None,
        default_color: QColor | None = None,
    ):
        super().__init__(parent)
        self.vm = vm
        self._dvs = dvs
        self.setWindowTitle("Derived signal" if dvs is None else f"Edit — {dvs.name}")
        self.resize(900, 600)

        initial_color = (dvs.color if dvs else None) or default_color or QColor("cyan")
        self.style_tab = StyleTab(initial_color=initial_color)
        self.filter_tab = FilterTab()

        self._build_ui()

        if dvs:
            self._load(dvs)

    # ---------------------------------------------------------------- #
    # Build                                                              #
    # ---------------------------------------------------------------- #

    def _build_ui(self):
        root = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_formula_tab(), "Formula")
        tabs.addTab(self.style_tab, "Style")
        tabs.addTab(self.filter_tab, "Filter")
        root.addWidget(tabs)

        # Bottom bar: preview result + OK/Cancel
        bar = QHBoxLayout()
        self._preview_label = QLabel("")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet("color: #aaa; font-style: italic;")
        bar.addWidget(self._preview_label, 1)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bar.addWidget(ok_btn)
        bar.addWidget(cancel_btn)
        root.addLayout(bar)

    def _build_formula_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)

        # ---- Left: name + editor + signal list + preview btn ----
        left = QVBoxLayout()
        left.setSpacing(4)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. rssi_ch1")
        name_row.addWidget(self._name_edit)
        left.addLayout(name_row)

        left.addWidget(QLabel("Formula:"))
        self._editor = QPlainTextEdit()
        mono = QFont("Consolas", 10)
        if not mono.exactMatch():
            mono = QFont("Courier New", 10)
        self._editor.setFont(mono)
        self._editor.setTabStopDistance(28)
        self._editor.setPlaceholderText(
            "# Write a Python script.\n"
            "# Assign:  result = (ts_array, y_array)\n"
        )
        left.addWidget(self._editor, 3)

        left.addWidget(QLabel("Signals in this plot (double-click to insert):"))
        self._signal_list = QListWidget()
        self._signal_list.setMaximumHeight(110)
        self._populate_signal_list()
        self._signal_list.itemDoubleClicked.connect(self._insert_signal_name)
        left.addWidget(self._signal_list)

        preview_btn = QPushButton("Preview (first 5 values)")
        preview_btn.clicked.connect(self._on_preview)
        left.addWidget(preview_btn)

        # ---- Right: reference panel ----
        ref_label = QPlainTextEdit()
        ref_label.setReadOnly(True)
        ref_label.setFont(QFont("Consolas", 9) if QFont("Consolas", 9).exactMatch() else QFont("Courier New", 9))
        ref_label.setPlainText(_REFERENCE)
        ref_label.setMinimumWidth(340)

        splitter = QSplitter(Qt.Horizontal)
        left_w = QWidget()
        left_w.setLayout(left)
        splitter.addWidget(left_w)
        splitter.addWidget(ref_label)
        splitter.setSizes([500, 400])

        layout.addWidget(splitter)
        return w

    # ---------------------------------------------------------------- #
    # Load existing                                                      #
    # ---------------------------------------------------------------- #

    def _load(self, dvs: DerivedViewSignal):
        self._name_edit.setText(dvs.derived.name)
        self._editor.setPlainText(dvs.derived.formula)
        self.style_tab.load_signal(dvs)
        self.filter_tab.load_signal(dvs)

    # ---------------------------------------------------------------- #
    # Signal list                                                        #
    # ---------------------------------------------------------------- #

    def _populate_signal_list(self):
        self._signal_list.clear()
        for name in self.vm.signals:
            self._signal_list.addItem(name)
        for name in self.vm.derived:
            self._signal_list.addItem(f"{name}  [derived]")

    def _insert_signal_name(self, item):
        raw = item.text()
        name = raw.split("  [")[0]
        cursor = self._editor.textCursor()
        cursor.insertText(repr(name))

    # ---------------------------------------------------------------- #
    # Preview                                                            #
    # ---------------------------------------------------------------- #

    def _on_preview(self):
        formula = self._editor.toPlainText().strip()
        if not formula:
            self._preview_label.setText("Formula is empty.")
            return
        try:
            decoded = {
                name: self.vm._decode_cached(vs.signal, vs.selector)
                for name, vs in self.vm.signals.items()
            }
            ctx = build_formula_context(self.vm.df, decoded)
            ts, y = evaluate(formula, ctx)
        except FormulaError as exc:
            self._preview_label.setStyleSheet("color: #ff6b6b; font-style: italic;")
            self._preview_label.setText(str(exc))
            return
        except Exception as exc:
            self._preview_label.setStyleSheet("color: #ff6b6b; font-style: italic;")
            self._preview_label.setText(f"Unexpected error: {exc}")
            return

        self._preview_label.setStyleSheet("color: #6bcb77; font-style: normal;")
        if len(y) == 0:
            self._preview_label.setText("Result: (empty)")
        else:
            sample = list(y[:5])
            self._preview_label.setText(
                f"Result ({len(y)} points): {sample}{' …' if len(y) > 5 else ''}"
            )

    # ---------------------------------------------------------------- #
    # OK                                                                 #
    # ---------------------------------------------------------------- #

    def _on_ok(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid name", "Signal name cannot be empty.")
            return

        existing_raw = set(self.vm.signals.keys())
        existing_derived = set(self.vm.derived.keys())
        editing_name = self._dvs.name if self._dvs else None

        if name in existing_raw:
            QMessageBox.warning(
                self, "Name conflict",
                f"'{name}' is already used by a regular signal."
            )
            return
        if name in existing_derived and name != editing_name:
            QMessageBox.warning(
                self, "Duplicate name",
                f"A derived signal named '{name}' already exists."
            )
            return

        self.accept()

    # ---------------------------------------------------------------- #
    # Result                                                             #
    # ---------------------------------------------------------------- #

    def get_derived_view_signal(self) -> DerivedViewSignal:
        name = self._name_edit.text().strip()
        formula = self._editor.toPlainText()
        style = self.style_tab.get_style()
        filter_type, filter_params = self.filter_tab.get_filter()

        ds = DerivedSignal(name=name, formula=formula)
        return DerivedViewSignal(
            derived=ds,
            color=style["color"],
            line_style=style["line_style"],
            line_width=style["line_width"],
            filter_type=filter_type,
            filter_params=filter_params,
            internal_id=(self._dvs.internal_id if self._dvs else None),
            marker_enabled=style.get("marker_enabled", False),
            marker_shape=style.get("marker_shape", "Circle"),
            marker_size=style.get("marker_size", 8),
            marker_color=style.get("marker_color"),
            marker_border_color=style.get("marker_border_color"),
            marker_border_width=style.get("marker_border_width", 1),
            value_format=style.get("value_format", "auto"),
            value_decimals=style.get("value_decimals", 6),
            value_unit=style.get("value_unit", ""),
            step_mode=style.get("step_mode", False),
        )
