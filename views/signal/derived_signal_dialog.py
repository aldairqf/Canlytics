from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from config.theme import get_active_theme
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QButtonGroup,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from models.derived_signal import DerivedSignal
from models.derived_view_signal import DerivedViewSignal
from services.formula_context import build_formula_context
from services.formula_evaluator import FormulaError, evaluate
from services.formula_generator import generate_formula
from views.signal.pipeline_builder import PipelineBuilder
from views.signal.tabs.filter_tab import FilterTab
from views.signal.tabs.style_tab import StyleTab

# ---------------------------------------------------------------------------
# Formula reference panel (Advanced mode only)
# ---------------------------------------------------------------------------

_REFERENCE_HTML = """\
<html><head><style type="text/css">
body { font-family: Consolas,"Courier New",monospace; font-size: 9pt;
       color: #d4d4d4; margin: 6px 10px; }
pre  { background-color: #1e1e1e; padding: 5px 8px;
       margin: 2px 0 10px 0; color: #d4d4d4; }
</style></head><body>

<b style="color:#569CD6">np</b>&nbsp;&nbsp; NumPy&nbsp;&nbsp;<span style="color:#777">np.where, np.abs, np.sqrt, np.array …</span><br>
<b style="color:#569CD6">math</b>&nbsp; Python math&nbsp;&nbsp;<span style="color:#777">math.pi, math.log, math.floor …</span>

<br><br><span style="color:#569CD6">&#9656;</span> <b>Decoded signal</b><br>
<b style="color:#DCDCAA">signal</b>(<span style="color:#9CDCFE">name</span>) &rarr; <span style="color:#4EC9B0">(ts, y)</span>&nbsp;&nbsp;<span style="color:#777">decoded signal from this plot</span>
<pre>ts, y = signal(<span style="color:#CE9178">'engine_rpm'</span>)</pre>

<span style="color:#569CD6">&#9656;</span> <b>Raw CAN &mdash; DBC bit addressing</b><br>
<b style="color:#DCDCAA">raw_bits</b>(<span style="color:#9CDCFE">can_id, start_bit, length</span>,<br>
&nbsp;&nbsp;byte_order=<span style="color:#CE9178">'LE'|'BE'</span>, mode=<span style="color:#CE9178">'exact'|'j1939'</span>,<br>
&nbsp;&nbsp;mux_start, mux_bytes, mux_value) &rarr; <span style="color:#4EC9B0">(ts, y)</span><br>
<span style="color:#777">&nbsp;&nbsp;LE: start_bit = LSB &nbsp;&middot;&nbsp; BE: start_bit = MSB</span>
<pre>ts, y = raw_bits(<span style="color:#B5CEA8">0x18FF0001</span>, <span style="color:#B5CEA8">16</span>, <span style="color:#B5CEA8">16</span>)
ts, y = raw_bits(<span style="color:#B5CEA8">0x18FF0001</span>, <span style="color:#B5CEA8">16</span>, <span style="color:#B5CEA8">8</span>, mux_start=<span style="color:#B5CEA8">0</span>, mux_bytes=<span style="color:#B5CEA8">1</span>, mux_value=<span style="color:#B5CEA8">2</span>)</pre>

<b style="color:#DCDCAA">bam_bits</b>(<span style="color:#9CDCFE">pgn, start_bit, length</span>,<br>
&nbsp;&nbsp;byte_order=<span style="color:#CE9178">'LE'|'BE'</span>, source=None,<br>
&nbsp;&nbsp;mux_start, mux_bytes, mux_value) &rarr; <span style="color:#4EC9B0">(ts, y)</span><br>
<span style="color:#777">&nbsp;&nbsp;Same addressing on reassembled J1939 BAM payloads</span>
<pre>ts, y = bam_bits(<span style="color:#B5CEA8">0xFF17</span>, <span style="color:#B5CEA8">144</span>, <span style="color:#B5CEA8">16</span>)&nbsp;&nbsp;<span style="color:#6A9955"># byte 18 &times; 8 = 144</span></pre>

<span style="color:#569CD6">&#9656;</span> <b>Raw CAN &mdash; byte offset</b><br>
<b style="color:#DCDCAA">raw_extract</b>(<span style="color:#9CDCFE">can_id, offset, n, dtype</span>, mode=<span style="color:#CE9178">'exact'</span>) &rarr; <span style="color:#4EC9B0">(ts, y)</span><br>
<b style="color:#DCDCAA">bam_extract</b>(<span style="color:#9CDCFE">pgn, offset, n, dtype</span>, source=None) &rarr; <span style="color:#4EC9B0">(ts, y)</span>
<pre>ts, y = raw_extract(<span style="color:#B5CEA8">0x18FF0001</span>, <span style="color:#B5CEA8">2</span>, <span style="color:#B5CEA8">2</span>, <span style="color:#CE9178">'uint16le'</span>)
ts, y = bam_extract(<span style="color:#B5CEA8">0xFF17</span>, <span style="color:#B5CEA8">18</span>, <span style="color:#B5CEA8">2</span>, <span style="color:#CE9178">'int16le'</span>)</pre>

<span style="color:#569CD6">&#9656;</span> <b>Low-level</b><br>
<b style="color:#DCDCAA">raw_frames</b>(<span style="color:#9CDCFE">can_id</span>, mode=<span style="color:#CE9178">'exact'</span>) &rarr; <span style="color:#4EC9B0">iter (ts, bytes)</span><br>
<b style="color:#DCDCAA">bam_messages</b>(<span style="color:#9CDCFE">pgn</span>, source=None) &rarr; <span style="color:#4EC9B0">list[BamMessage]</span>&nbsp;<span style="color:#777">(.timestamp, .data)</span><br>
<b style="color:#DCDCAA">decode_bytes</b>(<span style="color:#9CDCFE">data, offset, n, dtype</span>) &rarr; <span style="color:#4EC9B0">scalar</span><br>
<span style="color:#777">&nbsp;&nbsp;dtypes: uint8 int8 uint16le int16le uint16be int16be<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;uint32le int32le uint32be int32be float32le float32be …</span>

<br><span style="color:#569CD6">&#9656;</span> <b>align</b><br>
<b style="color:#DCDCAA">align</b>(*[(ts&#8321;,y&#8321;),(ts&#8322;,y&#8322;),…]) &rarr; <span style="color:#4EC9B0">(ts, [y&#8321;, y&#8322;, …])</span><br>
<span style="color:#777">&nbsp;&nbsp;Forward-fills each series onto the union timestamp axis.</span>
<pre>ts, (a, b) = align((ts_a, a), (ts_b, b))</pre>

<span style="color:#569CD6">&#9656;</span> <b>Result contract</b><br>
Formula <b>must</b> assign:<br>
&nbsp;&nbsp;<span style="color:#C586C0">result</span> = (ts_array, y_array)&nbsp;&nbsp;<span style="color:#777">&larr; with timestamps</span><br>
&nbsp;&nbsp;<span style="color:#C586C0">result</span> = y_array&nbsp;&nbsp;<span style="color:#777">&larr; values only</span>

<br><span style="color:#569CD6">&#9656;</span> <b>Examples</b>
<pre><span style="color:#6A9955"># Scale a decoded signal</span>
ts, y = signal(<span style="color:#CE9178">'engine_rpm'</span>)
result = ts, y / <span style="color:#B5CEA8">60.0</span></pre>
<pre><span style="color:#6A9955"># Combine two signals</span>
ts_a, a = signal(<span style="color:#CE9178">'pressure_hi'</span>)
ts_b, b = signal(<span style="color:#CE9178">'pressure_lo'</span>)
ts, (a, b) = align((ts_a, a), (ts_b, b))
result = ts, a - b</pre>
<pre><span style="color:#6A9955"># BAM: 16-bit signed at bit 144 of PGN 0xFF17</span>
ts, y = bam_bits(<span style="color:#B5CEA8">0xFF17</span>, <span style="color:#B5CEA8">144</span>, <span style="color:#B5CEA8">16</span>)
y = np.where(y &gt;= <span style="color:#B5CEA8">2</span>**<span style="color:#B5CEA8">15</span>, y - <span style="color:#B5CEA8">2</span>**<span style="color:#B5CEA8">16</span>, y)
result = ts, y</pre>
<pre><span style="color:#6A9955"># BAM chunk loop</span>
ts_out, val_out = [], []
<span style="color:#C586C0">for</span> msg <span style="color:#C586C0">in</span> bam_messages(<span style="color:#B5CEA8">0xFF17</span>):
    <span style="color:#C586C0">for</span> i <span style="color:#C586C0">in</span> range(<span style="color:#B5CEA8">0</span>, len(msg.data), <span style="color:#B5CEA8">20</span>):
        chunk = msg.data[i : i + <span style="color:#B5CEA8">20</span>]
        <span style="color:#C586C0">if</span> len(chunk) == <span style="color:#B5CEA8">20</span>:
            ts_out.append(msg.timestamp)
            val_out.append(decode_bytes(chunk, <span style="color:#B5CEA8">18</span>, <span style="color:#B5CEA8">2</span>, <span style="color:#CE9178">'int16le'</span>))
result = np.array(ts_out), np.array(val_out)</pre>

</body></html>"""


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

        # Track the pipeline config from the last time we were in Basic mode.
        # None means "this signal has no Basic representation" (pure Advanced).
        self._current_simple_config: dict | None = (
            dvs.derived.simple_config if dvs else {}
        )

        self.result_action: str = "ok"  # "ok" | "duplicate" | "delete"

        self.setWindowTitle("Derived signal" if dvs is None else f"Edit — {dvs.name}")
        self.resize(960, 640)

        initial_color = (dvs.color if dvs else None) or default_color or QColor("cyan")
        self.style_tab = StyleTab(initial_color=initial_color)
        self.filter_tab = FilterTab()

        self._build_ui()

        if dvs:
            self._load(dvs)

        # Mode toggle hidden — always open in Advanced.
        # To re-enable Basic/Advanced switching: uncomment the block below
        # and uncomment the mode_row / connections in _build_formula_tab.
        # if dvs is not None and dvs.derived.simple_config is None:
        #     self._advanced_radio.setChecked(True)
        #     self._mode_stack.setCurrentIndex(1)
        #     self._code_section.setVisible(False)
        # else:
        #     self._basic_radio.setChecked(True)
        #     self._mode_stack.setCurrentIndex(0)
        #     self._code_section.setVisible(True)
        #     if self._current_simple_config:
        #         self._pipeline_builder.load_config(self._current_simple_config)
        self._advanced_radio.setChecked(True)
        self._mode_stack.setCurrentIndex(1)
        self._code_section.setVisible(False)

    # ------------------------------------------------------------------ #
    # Build                                                                #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        root = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_formula_tab(), "Formula")
        tabs.addTab(self.style_tab, "Style")
        tabs.addTab(self.filter_tab, "Filter")
        root.addWidget(tabs)

        # Bottom bar
        bar = QHBoxLayout()
        self._preview_label = QLabel("")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(f"color: {get_active_theme().text_muted}; font-style: italic;")
        bar.addWidget(self._preview_label, 1)

        preview_btn = QPushButton("Preview")
        preview_btn.clicked.connect(self._on_preview)
        bar.addWidget(preview_btn)

        if self._dvs:
            del_btn = QPushButton("Delete")
            del_btn.clicked.connect(self._on_delete)
            dup_btn = QPushButton("Duplicate")
            dup_btn.clicked.connect(self._on_duplicate)
            bar.addWidget(del_btn)
            bar.addWidget(dup_btn)

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
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ---- Mode toggle (hidden — always Advanced) --------------------- #
        mode_row = QHBoxLayout()
        self._basic_radio = QRadioButton("Basic")
        self._advanced_radio = QRadioButton("Advanced")
        # QButtonGroup keeps exclusivity even though mode_row stays unparented.
        self._mode_group = QButtonGroup(w)
        self._mode_group.addButton(self._basic_radio)
        self._mode_group.addButton(self._advanced_radio)
        self._basic_radio.setChecked(True)
        mode_row.addWidget(self._basic_radio)
        mode_row.addWidget(self._advanced_radio)
        mode_row.addStretch()
        # layout.addLayout(mode_row)  # toggle hidden

        # ---- Name ------------------------------------------------------- #
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. rssi_ch1")
        name_row.addWidget(self._name_edit)
        layout.addLayout(name_row)

        # ---- Mode stack ------------------------------------------------- #
        self._mode_stack = QStackedWidget()

        # Page 0: Basic — PipelineBuilder wrapped in a scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._pipeline_builder = PipelineBuilder(
            available_signals=list(self.vm.signals.keys()),
            df=self.vm.df,
        )
        scroll.setWidget(self._pipeline_builder)
        self._mode_stack.addWidget(scroll)

        # Page 1: Advanced — editor + signal list + reference panel
        self._mode_stack.addWidget(self._build_advanced_page())

        layout.addWidget(self._mode_stack, 1)

        # ---- Generated-code panel (Basic mode only) --------------------- #
        self._code_section = QGroupBox("Advanced: generated formula", self)
        self._code_section.setCheckable(True)
        self._code_section.setChecked(False)
        code_vbox = QVBoxLayout(self._code_section)
        code_vbox.setSpacing(2)
        self._generated_code_edit = QPlainTextEdit()
        self._generated_code_edit.setReadOnly(True)
        self._generated_code_edit.setMaximumHeight(120)
        mono = QFont("Consolas", 9)
        if not mono.exactMatch():
            mono = QFont("Courier New", 9)
        self._generated_code_edit.setFont(mono)
        self._generated_code_edit.setVisible(False)
        code_vbox.addWidget(self._generated_code_edit)
        self._code_section.toggled.connect(self._toggle_code_panel)
        # layout.addWidget(self._code_section)  # hidden with mode toggle

        # ---- Connections ------------------------------------------------ #
        # self._basic_radio.clicked.connect(lambda: self._set_mode(True))    # toggle hidden
        # self._advanced_radio.clicked.connect(lambda: self._set_mode(False))  # toggle hidden
        # self._pipeline_builder.changed.connect(self._on_pipeline_changed)  # toggle hidden

        return w

    def _build_advanced_page(self) -> QWidget:
        """Right side: formula editor + signal list | reference panel."""
        left = QVBoxLayout()
        left.setSpacing(4)

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

        ref = QTextBrowser()
        ref.setOpenLinks(False)
        ref.setHtml(_REFERENCE_HTML)
        ref.setMinimumWidth(340)

        splitter = QSplitter(Qt.Horizontal)
        left_w = QWidget()
        left_w.setLayout(left)
        splitter.addWidget(left_w)
        splitter.addWidget(ref)
        splitter.setSizes([520, 400])
        return splitter

    # ------------------------------------------------------------------ #
    # Load existing                                                        #
    # ------------------------------------------------------------------ #

    def _load(self, dvs: DerivedViewSignal):
        self._name_edit.setText(dvs.derived.name)
        self._editor.setPlainText(dvs.derived.formula)
        self.style_tab.load_signal(dvs)
        self.filter_tab.load_signal(dvs)
        # Pipeline builder loaded in __init__ from simple_config

    # ------------------------------------------------------------------ #
    # Mode toggle                                                          #
    # ------------------------------------------------------------------ #

    def _set_mode(self, basic: bool):
        if basic:
            if self._current_simple_config is not None:
                # Reload builder from saved state and switch page
                self._pipeline_builder.load_config(self._current_simple_config)
                self._mode_stack.setCurrentIndex(0)
                self._code_section.setVisible(True)
            else:
                QMessageBox.information(
                    self, "Cannot switch to Basic mode",
                    "This formula uses custom logic that cannot be represented in "
                    "Basic mode.\nContinue editing it in Advanced mode.",
                )
                # Revert toggle (programmatic — won't retrigger clicked)
                self._advanced_radio.setChecked(True)
                self._basic_radio.setChecked(False)
        else:
            # Basic → Advanced: snapshot current pipeline config, generate code
            try:
                cfg = self._pipeline_builder.get_config()
                self._current_simple_config = cfg
                code = generate_formula(cfg)
                self._editor.setPlainText(code)
            except (ValueError, Exception):
                pass
            self._mode_stack.setCurrentIndex(1)
            self._code_section.setVisible(False)

    # ------------------------------------------------------------------ #
    # Generated-code panel                                                 #
    # ------------------------------------------------------------------ #

    def _toggle_code_panel(self, visible: bool):
        self._generated_code_edit.setVisible(visible)
        if visible:
            self._refresh_generated_code()

    def _on_pipeline_changed(self):
        self._preview_label.setText("")  # stale preview
        if self._generated_code_edit.isVisible():
            self._refresh_generated_code()

    def _refresh_generated_code(self):
        try:
            cfg = self._pipeline_builder.get_config()
            code = generate_formula(cfg)
            self._generated_code_edit.setPlainText(code)
        except (ValueError, Exception) as exc:
            self._generated_code_edit.setPlainText(f"# Config error: {exc}")

    # ------------------------------------------------------------------ #
    # Signal list (Advanced page)                                          #
    # ------------------------------------------------------------------ #

    def _populate_signal_list(self):
        self._signal_list.clear()
        for name in self.vm.signals:
            self._signal_list.addItem(name)
        for name in self.vm.derived:
            self._signal_list.addItem(f"{name}  [derived]")

    def _insert_signal_name(self, item):
        name = item.text().split("  [")[0]
        cursor = self._editor.textCursor()
        cursor.insertText(repr(name))

    # ------------------------------------------------------------------ #
    # Preview                                                              #
    # ------------------------------------------------------------------ #

    def _on_preview(self):
        if self._basic_radio.isChecked():
            try:
                cfg = self._pipeline_builder.get_config()
                formula = generate_formula(cfg)
            except (ValueError, Exception) as exc:
                self._preview_label.setStyleSheet(f"color: {get_active_theme().error}; font-style: italic;")
                self._preview_label.setText(f"Config error: {exc}")
                return
        else:
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
            self._preview_label.setStyleSheet(f"color: {get_active_theme().error}; font-style: italic;")
            self._preview_label.setText(str(exc))
            return
        except Exception as exc:
            self._preview_label.setStyleSheet(f"color: {get_active_theme().error}; font-style: italic;")
            self._preview_label.setText(f"Unexpected error: {exc}")
            return

        self._preview_label.setStyleSheet(f"color: {get_active_theme().success}; font-style: normal;")
        if len(y) == 0:
            self._preview_label.setText("Result: (empty)")
        else:
            sample = list(y[:5])
            self._preview_label.setText(
                f"Result ({len(y)} points): {sample}{' …' if len(y) > 5 else ''}"
            )

    # ------------------------------------------------------------------ #
    # OK                                                                   #
    # ------------------------------------------------------------------ #

    def _on_delete(self):
        self.result_action = "delete"
        self.accept()

    def _on_duplicate(self):
        self.result_action = "duplicate"
        self._on_ok()

    def _on_ok(self):
        name = self._name_edit.text().strip()
        # An empty name is allowed: get_derived_view_signal() assigns a unique default.
        if name:
            existing_raw = set(self.vm.signals.keys())
            existing_derived = set(self.vm.derived.keys())
            editing_name = self._dvs.name if self._dvs else None

            if name in existing_raw:
                QMessageBox.warning(
                    self, "Name conflict",
                    f"'{name}' is already used by a regular signal.",
                )
                return
            if name in existing_derived and name != editing_name:
                QMessageBox.warning(
                    self, "Duplicate name",
                    f"A derived signal named '{name}' already exists.",
                )
                return

        self.accept()

    # ------------------------------------------------------------------ #
    # Result                                                               #
    # ------------------------------------------------------------------ #

    def get_derived_view_signal(self) -> DerivedViewSignal:
        name = self._name_edit.text().strip()
        if not name:
            taken = set(self.vm.signals) | set(self.vm.derived)
            name, index = "Derived", 1
            while name in taken:
                name = f"Derived_{index}"
                index += 1
        style = self.style_tab.get_style()
        filter_type, filter_params = self.filter_tab.get_filter()

        if self._basic_radio.isChecked():
            cfg = self._pipeline_builder.get_config()
            formula = generate_formula(cfg)
            simple_config: dict | None = cfg
        else:
            formula = self._editor.toPlainText()
            simple_config = None

        ds = DerivedSignal(name=name, formula=formula, simple_config=simple_config)
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
