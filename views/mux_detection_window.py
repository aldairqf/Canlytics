from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from viewmodels.mux_detection_viewmodel import MuxDetectionViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.settings.time_config_dialog import TimeConfigDialog
from views.settings.time_filter_dialog import TimeFilterDialog


class MuxDetectionWindow(QMainWindow):
    def __init__(
        self,
        vm: MuxDetectionViewModel,
        *,
        time_config_vm: TimeConfigViewModel,
        timezone_mode: str = "none",
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("mux_detection_title"))
        self.resize(1550, 950)
        self._vm = vm
        self._time_vm = time_config_vm
        self._timezone_mode = timezone_mode
        self._progress: QProgressDialog | None = None
        self._results: list[dict[str, Any]] = []
        self._current_result: dict[str, Any] | None = None
        self._time_filter_state: dict[str, str] = {}
        self._build_ui()
        self._setup_menu_bar()
        self._wire()
        self._apply_strictness_defaults()
        self._vm.set_dataframe(getattr(self._vm, "_df", None))

    def _build_ui(self) -> None:
        self.tabs = QTabWidget(self)
        self.setCentralWidget(self.tabs)

        self._build_configuration_tab()
        self._build_results_tab()

    def _build_configuration_tab(self) -> None:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        self.signal_list = QListWidget(self)
        self.signal_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Search CAN ID...")
        self.btn_select_all = QPushButton(get_text("select_all"), self)
        self.btn_select_none = QPushButton(get_text("select_none"), self)
        self.btn_analyze = QPushButton(get_text("mux_detection_analyze"), self)

        left_buttons = QHBoxLayout()
        left_buttons.addWidget(self.btn_select_all)
        left_buttons.addWidget(self.btn_select_none)

        prefix_group = QGroupBox("Mux discovery", self)
        prefix_form = QFormLayout(prefix_group)
        self.strictness = QSlider(Qt.Horizontal, self)
        self.strictness.setRange(0, 100)
        self.strictness.setValue(55)
        self.strictness_value = QLabel("55", self)
        self.strictness_summary = QLabel(self)
        prefix_form.addRow("Sensitivity", self._strictness_row())
        prefix_form.addRow("Min dependency score", self.strictness_summary)

        self.chk_prefix_2 = QCheckBox("Try 2-byte ranges", self)
        self.chk_prefix_2.setChecked(True)
        self.chk_prefix_1 = QCheckBox("Try 1-byte ranges", self)
        self.chk_prefix_1.setChecked(True)
        self.chk_prefix_3 = QCheckBox("Try 3-byte ranges", self)
        self.chk_prefix_3.setChecked(True)
        self.chk_prefix_4 = QCheckBox("Try 4-byte ranges", self)
        self.chk_prefix_4.setChecked(True)
        prefix_form.addRow(self.chk_prefix_1)
        prefix_form.addRow(self.chk_prefix_2)
        prefix_form.addRow(self.chk_prefix_3)
        prefix_form.addRow(self.chk_prefix_4)

        self.spin_min_support = QSpinBox(self)
        self.spin_min_support.setRange(2, 10000)
        self.spin_min_support.setValue(10)
        self.spin_max_cardinality = QSpinBox(self)
        self.spin_max_cardinality.setRange(2, 256)
        self.spin_max_cardinality.setValue(32)
        prefix_form.addRow("Min support (frames)", self.spin_min_support)
        prefix_form.addRow("Max distinct values", self.spin_max_cardinality)

        decode_group = QGroupBox("Quick payload decode", self)
        decode_form = QFormLayout(decode_group)
        self.chk_decode_int_uint = QCheckBox("Try uint / int", self)
        self.chk_decode_int_uint.setChecked(True)
        self.chk_decode_float32 = QCheckBox("Try float32", self)
        self.chk_decode_float32.setChecked(True)
        self.chk_decode_bitfields = QCheckBox("Try bitfields", self)
        self.spin_max_decodes = QSpinBox(self)
        self.spin_max_decodes.setRange(1, 50)
        decode_form.addRow(self.chk_decode_int_uint)
        decode_form.addRow(self.chk_decode_float32)
        decode_form.addRow(self.chk_decode_bitfields)
        decode_form.addRow("Max decode candidates", self.spin_max_decodes)

        # Tuning knobs are secondary to the common "select groups, hit
        # Analyze" flow -- collapsed behind a toggle by default, same
        # pattern as Analyze Data's "Statistics" panel.
        self.btn_advanced = QPushButton("▸  Advanced", self)
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.setChecked(False)
        self.btn_advanced.setObjectName("stats_toggle")
        self.btn_advanced.setFixedHeight(28)

        self.advanced_panel = QWidget(self)
        self.advanced_panel.setVisible(False)
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.addWidget(prefix_group)
        advanced_layout.addWidget(decode_group)

        layout.addWidget(QLabel("CAN groups"))
        layout.addLayout(left_buttons)
        layout.addWidget(self.search_box)
        layout.addWidget(self.signal_list, 1)
        layout.addWidget(self.btn_advanced)
        layout.addWidget(self.advanced_panel)
        layout.addWidget(self.btn_analyze)

        self.tabs.addTab(tab, "Configuration")

    def _build_results_tab(self) -> None:
        tab = QWidget(self)
        outer = QHBoxLayout(tab)

        self.result_groups = QListWidget(self)

        self.patterns_table = QTableWidget(0, 10, self)
        self.patterns_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.patterns_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.patterns_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.patterns_table.setAlternatingRowColors(True)
        self.patterns_table.setHorizontalHeaderLabels(
            ["Byte range", "Width", "Cardinality", "Support", "Coverage", "Info gain", "Counter-like", "Recommended", "Top decode", "Reason"]
        )
        self.patterns_table.verticalHeader().setVisible(False)

        self.decode_table = QTableWidget(0, 9, self)
        self.decode_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.decode_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.decode_table.setAlternatingRowColors(True)
        self.decode_table.setHorizontalHeaderLabels(
            ["Candidate", "Type", "Byte range", "Endian", "Score", "Unique", "Change", "Min", "Max"]
        )
        self.decode_table.verticalHeader().setVisible(False)

        self.sample_frames_table = QTableWidget(0, 2, self)
        self.sample_frames_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sample_frames_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.sample_frames_table.setAlternatingRowColors(True)
        self.sample_frames_table.setHorizontalHeaderLabels(["TS", "Frame"])
        self.sample_frames_table.verticalHeader().setVisible(False)

        self.summary = QPlainTextEdit(self)
        self.summary.setReadOnly(True)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Analyzed groups"))
        left_layout.addWidget(self.result_groups, 1)

        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.addWidget(QLabel("Exact subframe patterns"))
        center_layout.addWidget(self.patterns_table, 2)
        center_layout.addWidget(QLabel("Decode candidates"))
        center_layout.addWidget(self.decode_table, 2)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Pattern detail"))
        right_layout.addWidget(self.summary, 2)
        right_layout.addWidget(QLabel("Sample frames"))
        right_layout.addWidget(self.sample_frames_table, 2)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter)

        self.tabs.addTab(tab, "Results")

    def _strictness_row(self) -> QWidget:
        wrapper = QWidget(self)
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.strictness, 1)
        layout.addWidget(self.strictness_value)
        return wrapper

    def _wire(self) -> None:
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_select_none.clicked.connect(self._select_none)
        self.btn_analyze.clicked.connect(self._analyze)
        self.search_box.textChanged.connect(self._apply_search_filter)
        self.strictness.valueChanged.connect(self._on_strictness_changed)
        self.btn_advanced.toggled.connect(self._toggle_advanced_panel)
        self.result_groups.currentRowChanged.connect(self._on_group_changed)
        self.patterns_table.itemSelectionChanged.connect(self._on_pattern_selection_changed)

        self._vm.available_signals_changed.connect(self._set_signals)
        self._vm.results_changed.connect(self._set_results)
        self._vm.analysis_started.connect(self._on_analysis_started)
        self._vm.analysis_finished.connect(self._hide_progress)
        self._vm.analysis_failed.connect(self._set_error)

    def _setup_menu_bar(self) -> None:
        menu = self.menuBar().addMenu(get_text("menu_settings"))
        action = menu.addAction(get_text("menu_time_config"))
        action.triggered.connect(self._open_time_settings)
        time_filter_action = menu.addAction(get_text("menu_time_filter"))
        time_filter_action.triggered.connect(self._open_time_filter)

    def _open_time_settings(self) -> None:
        dlg = TimeConfigDialog(self._time_vm, parent=self)
        dlg.exec()

    def _open_time_filter(self) -> None:
        dlg = TimeFilterDialog(self._time_vm, state=self._time_filter_state, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._time_filter_state = dlg.get_state()
        ts_min, ts_max = dlg.get_range()
        self._vm.set_time_range(ts_min, ts_max)

    def _toggle_advanced_panel(self, visible: bool) -> None:
        self.advanced_panel.setVisible(visible)
        self.btn_advanced.setText("▾  Advanced" if visible else "▸  Advanced")

    def _set_signals(self, signals: list[tuple[str, int]]) -> None:
        self.signal_list.blockSignals(True)
        self.signal_list.clear()
        for can_id, frame_len in signals:
            item = QListWidgetItem(f"{can_id} | LEN {frame_len}")
            item.setData(Qt.UserRole, (can_id, frame_len))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
            self.signal_list.addItem(item)
        self.signal_list.blockSignals(False)
        self._apply_search_filter()

    def _apply_search_filter(self) -> None:
        needle = (self.search_box.text() or "").strip().upper()
        for row in range(self.signal_list.count()):
            item = self.signal_list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().upper())

    def _select_all(self) -> None:
        for row in range(self.signal_list.count()):
            item = self.signal_list.item(row)
            if item:
                item.setCheckState(Qt.Checked)

    def _select_none(self) -> None:
        for row in range(self.signal_list.count()):
            item = self.signal_list.item(row)
            if item:
                item.setCheckState(Qt.Unchecked)

    def _on_strictness_changed(self, value: int) -> None:
        self.strictness_value.setText(str(int(value)))
        self._apply_strictness_defaults()

    def _apply_strictness_defaults(self) -> None:
        # Sensitivity is the only value derived from the slider -- it maps to a
        # single threshold (min dependency score); every other option below is
        # a direct, independent control.
        sensitivity = max(0, min(int(self.strictness.value()), 100)) / 100.0
        min_nmi = 0.70 - (0.40 * sensitivity)
        self.strictness_summary.setText(f"{min_nmi:.2f} (0..1, higher = stricter)")

    def _selected_candidate_widths(self) -> tuple[int, ...]:
        widths: list[int] = []
        if self.chk_prefix_1.isChecked():
            widths.append(1)
        if self.chk_prefix_2.isChecked():
            widths.append(2)
        if self.chk_prefix_3.isChecked():
            widths.append(3)
        if self.chk_prefix_4.isChecked():
            widths.append(4)
        return tuple(widths or [1, 2, 3, 4])

    def _options(self) -> dict[str, Any]:
        return {
            "sensitivity": self.strictness.value(),
            "candidate_widths": self._selected_candidate_widths(),
            "min_support": self.spin_min_support.value(),
            "max_cardinality": self.spin_max_cardinality.value(),
            "decode_int_uint": self.chk_decode_int_uint.isChecked(),
            "decode_float32": self.chk_decode_float32.isChecked(),
            "decode_bitfields": self.chk_decode_bitfields.isChecked(),
            "max_decode_candidates": self.spin_max_decodes.value(),
        }

    def _analyze(self) -> None:
        selected_groups: list[tuple[str, int]] = []
        for row in range(self.signal_list.count()):
            item = self.signal_list.item(row)
            if item and item.checkState() == Qt.Checked:
                selected_groups.append(item.data(Qt.UserRole))
        self._vm.start_analysis(selected_groups=selected_groups, options=self._options())

    def _set_results(self, results: list[dict[str, Any]]) -> None:
        self._results = results
        self.result_groups.blockSignals(True)
        self.result_groups.clear()
        for result in results:
            analysis = result.get("analysis") or {}
            text = (
                f"{result['label']} | candidates {analysis.get('candidate_count', 0)}"
                f" | best {analysis.get('best_candidate') or '-'}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, result)
            self.result_groups.addItem(item)
        self.result_groups.blockSignals(False)
        self._current_result = None
        self.patterns_table.setRowCount(0)
        self.decode_table.setRowCount(0)
        self.sample_frames_table.setRowCount(0)
        self.summary.clear()
        if results:
            self.tabs.setCurrentIndex(1)
            self.result_groups.setCurrentRow(0)

    def _on_group_changed(self, row: int) -> None:
        self.patterns_table.setRowCount(0)
        self.decode_table.setRowCount(0)
        self.sample_frames_table.setRowCount(0)
        self.summary.clear()
        self._current_result = None
        if row < 0 or row >= self.result_groups.count():
            return
        result = self.result_groups.item(row).data(Qt.UserRole)
        self._current_result = result
        analysis = result.get("analysis") or {}
        candidates = analysis.get("candidates", [])
        for row_idx, candidate in enumerate(candidates):
            self.patterns_table.insertRow(row_idx)
            values = [
                _format_range(candidate.get("byte_range")),
                str(candidate.get("width", "")),
                str(candidate.get("cardinality", "")),
                str(candidate.get("support", "")),
                f"{float(candidate.get('coverage_ratio', 0.0)):.3f}",
                f"{float(candidate.get('information_gain', 0.0)):.3f}",
                "yes" if candidate.get("counter_like") else "no",
                "yes" if candidate.get("recommended") else "no",
                str((candidate.get("top_decode") or {}).get("label") or "-"),
                str(candidate.get("reason", "")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, candidate)
                if col == len(values) - 1:  # Reason: full sentence, keep it readable via tooltip
                    item.setToolTip(value)
                self.patterns_table.setItem(row_idx, col, item)
        self.patterns_table.resizeColumnsToContents()
        # The Reason column is a full sentence -- resizeColumnsToContents()
        # would size it to fit on one line (1000+ px), ballooning the whole
        # window's minimum size. Cap it and let long text wrap/elide instead.
        reason_col = self.patterns_table.columnCount() - 1
        self.patterns_table.setColumnWidth(reason_col, min(320, self.patterns_table.columnWidth(reason_col)))
        self.patterns_table.setWordWrap(True)
        self.patterns_table.resizeRowsToContents()
        if candidates:
            self.patterns_table.selectRow(0)
            self._show_pattern(candidates[0], analysis)

    def _on_pattern_selection_changed(self) -> None:
        items = self.patterns_table.selectedItems()
        if not items or self._current_result is None:
            return
        row = items[0].row()
        item = self.patterns_table.item(row, 0)
        candidate = item.data(Qt.UserRole) if item else None
        if candidate is None:
            return
        analysis = (self._current_result or {}).get("analysis") or {}
        self._show_pattern(candidate, analysis)

    def _show_pattern(self, candidate: dict[str, Any], analysis: dict[str, Any]) -> None:
        top_decode = candidate.get("top_decode") or {}
        self.summary.setPlainText(
            "\n".join(
                [
                    f"CAN ID: {analysis.get('can_id', self._current_result.get('can_id') if self._current_result else '-')}",
                    f"Frame length: {analysis.get('frame_len', '-')}",
                    f"Byte range: {_format_range(candidate.get('byte_range'))}",
                    f"Cardinality: {candidate.get('cardinality', '-')}",
                    f"Support: {candidate.get('support', 0)} ({float(candidate.get('coverage_ratio', 0.0)):.3f} coverage)",
                    f"Information gain (NMI): {float(candidate.get('information_gain', 0.0)):.3f}",
                    f"Counter-like: {'yes' if candidate.get('counter_like') else 'no'}",
                    f"Recommended: {'yes' if candidate.get('recommended') else 'no'}",
                    f"Top decode: {top_decode.get('label') or '-'}",
                    f"Reason: {candidate.get('reason', '-')}",
                ]
            )
        )
        self._set_decode_table([top_decode] if top_decode else [])
        self._set_sample_frames(candidate.get("sample_frames", []))

    def _set_decode_table(self, decode_candidates: list[dict[str, Any]]) -> None:
        self.decode_table.setRowCount(0)
        for row, candidate in enumerate(decode_candidates):
            self.decode_table.insertRow(row)
            values = [
                str(candidate.get("label", "")),
                str(candidate.get("kind", "")),
                _format_range(candidate.get("byte_range")),
                str(candidate.get("endian") or "-"),
                f"{float(candidate.get('score', 0.0)):.3f}",
                str(candidate.get("unique_values", "")),
                f"{float(candidate.get('change_rate', 0.0)):.3f}",
                _format_optional(candidate.get("min_value")),
                _format_optional(candidate.get("max_value")),
            ]
            for col, value in enumerate(values):
                self.decode_table.setItem(row, col, QTableWidgetItem(value))
        self.decode_table.resizeColumnsToContents()

    def _set_sample_frames(self, sample_frames: list[dict[str, Any]]) -> None:
        self.sample_frames_table.setRowCount(0)
        for row, frame in enumerate(sample_frames):
            self.sample_frames_table.insertRow(row)
            self.sample_frames_table.setItem(row, 0, QTableWidgetItem(f"{float(frame.get('timestamp', 0.0)):.6f}"))
            self.sample_frames_table.setItem(row, 1, QTableWidgetItem(str(frame.get("payload_hex", ""))))
        self.sample_frames_table.resizeColumnsToContents()

    def _set_error(self, message: str) -> None:
        self.summary.setPlainText(message)
        self.tabs.setCurrentIndex(1)

    def _show_progress(self, message: str) -> None:
        self._progress = QProgressDialog(message, "", 0, 0, self)
        self._progress.setWindowTitle(get_text("mux_detection_title"))
        self._progress.setCancelButton(None)
        self._progress.setWindowModality(Qt.ApplicationModal)
        self._progress.show()
        QApplication.processEvents()

    def _hide_progress(self) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None

    def _on_analysis_started(self) -> None:
        self._show_progress(get_text("mux_detection_loading"))

    def closeEvent(self, event) -> None:
        try:
            self._vm.available_signals_changed.disconnect(self._set_signals)
        except (TypeError, RuntimeError):
            pass
        try:
            self._vm.results_changed.disconnect(self._set_results)
        except (TypeError, RuntimeError):
            pass
        try:
            self._vm.analysis_failed.disconnect(self._set_error)
        except (TypeError, RuntimeError):
            pass
        try:
            self._vm.analysis_started.disconnect(self._on_analysis_started)
        except (TypeError, RuntimeError):
            pass
        try:
            self._vm.analysis_finished.disconnect(self._hide_progress)
        except (TypeError, RuntimeError):
            pass
        self._hide_progress()
        super().closeEvent(event)


def _format_range(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{value[0]}..{value[1]}"
    return str(value)


def _format_optional(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)
