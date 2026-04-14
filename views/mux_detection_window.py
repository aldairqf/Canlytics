from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QProgressDialog,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from viewmodels.mux_detection_viewmodel import MuxDetectionViewModel


class MuxDetectionWindow(QMainWindow):
    def __init__(self, vm: MuxDetectionViewModel, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("mux_detection_title"))
        self.resize(1500, 900)
        self._vm = vm
        self._progress: QProgressDialog | None = None
        self._results: list[dict] = []
        self._build_ui()
        self._wire()
        self._vm.set_dataframe(getattr(self._vm, "_df", None))

    def _build_ui(self) -> None:
        self.signal_list = QListWidget(self)
        self.signal_list.setSelectionMode(QAbstractItemView.NoSelection)

        self.btn_select_all = QPushButton(get_text("select_all"), self)
        self.btn_select_none = QPushButton(get_text("select_none"), self)
        self.btn_analyze = QPushButton(get_text("mux_detection_analyze"), self)
        self.chk_hide_without_candidates = QCheckBox(get_text("mux_detection_hide_without_candidates"), self)
        self.chk_hide_without_candidates.setChecked(False)

        self.chk_change_rate = QCheckBox(get_text("mux_detection_use_change_rate"), self)
        self.chk_change_rate.setChecked(True)
        self.chk_unique_ratio = QCheckBox(get_text("mux_detection_use_unique_ratio"), self)
        self.chk_unique_ratio.setChecked(True)
        self.chk_periodicity = QCheckBox(get_text("mux_detection_use_periodicity"), self)
        self.chk_periodicity.setChecked(True)
        self.chk_nmi = QCheckBox(get_text("mux_detection_use_nmi"), self)
        self.chk_nmi.setChecked(True)
        self.chk_entropy = QCheckBox(get_text("mux_detection_use_entropy"), self)
        self.chk_entropy.setChecked(False)
        self.chk_window_entropy = QCheckBox(get_text("mux_detection_use_window_entropy"), self)
        self.chk_window_entropy.setChecked(False)
        self.chk_bitfields = QCheckBox(get_text("mux_detection_use_bitfields"), self)
        self.chk_bitfields.setChecked(False)
        self.chk_early_state_presence = QCheckBox(get_text("mux_detection_require_early_states"), self)
        self.chk_early_state_presence.setChecked(False)
        self.strictness = QSlider(Qt.Horizontal, self)
        self.strictness.setRange(0, 100)
        self.strictness.setValue(55)
        self.strictness_value = QLabel("55", self)

        conditions = QWidget(self)
        conditions_layout = QVBoxLayout(conditions)
        conditions_layout.addWidget(QLabel(get_text("mux_detection_conditions")))
        for widget in (
            self.chk_change_rate,
            self.chk_unique_ratio,
            self.chk_periodicity,
            self.chk_nmi,
            self.chk_entropy,
            self.chk_window_entropy,
            self.chk_bitfields,
            self.chk_early_state_presence,
        ):
            conditions_layout.addWidget(widget)
        conditions_layout.addWidget(QLabel(get_text("mux_detection_strictness")))
        conditions_layout.addWidget(self.strictness)
        strictness_row = QHBoxLayout()
        strictness_row.addWidget(QLabel(get_text("mux_detection_strictness_low")))
        strictness_row.addStretch(1)
        strictness_row.addWidget(self.strictness_value)
        strictness_row.addStretch(1)
        strictness_row.addWidget(QLabel(get_text("mux_detection_strictness_high")))
        conditions_layout.addLayout(strictness_row)
        conditions_layout.addStretch(1)

        left_buttons = QHBoxLayout()
        left_buttons.addWidget(self.btn_select_all)
        left_buttons.addWidget(self.btn_select_none)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel(get_text("mux_detection_signals")))
        left_layout.addLayout(left_buttons)
        left_layout.addWidget(self.signal_list, 1)
        left_layout.addWidget(conditions)
        left_layout.addWidget(self.chk_hide_without_candidates)
        left_layout.addWidget(self.btn_analyze)

        self.result_groups = QListWidget(self)
        self.result_candidates = QListWidget(self)
        self.summary = QPlainTextEdit(self)
        self.summary.setReadOnly(True)
        self.relationships = QPlainTextEdit(self)
        self.relationships.setReadOnly(True)

        self.states_table = QTableWidget(0, 2, self)
        self.states_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.states_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.states_table.setAlternatingRowColors(True)
        self.states_table.setHorizontalHeaderLabels(
            [
                get_text("mux_detection_state_value"),
                get_text("mux_detection_state_count"),
            ]
        )
        self.states_table.verticalHeader().setVisible(False)

        self.periods_table = QTableWidget(0, 4, self)
        self.periods_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.periods_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.periods_table.setAlternatingRowColors(True)
        self.periods_table.setHorizontalHeaderLabels(
            [
                get_text("mux_detection_period_state"),
                get_text("mux_detection_period_median"),
                get_text("mux_detection_period_mean"),
                get_text("mux_detection_period_cv"),
            ]
        )
        self.periods_table.verticalHeader().setVisible(False)

        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.addWidget(QLabel(get_text("mux_detection_results")))
        center_layout.addWidget(self.result_groups, 1)
        center_layout.addWidget(QLabel(get_text("mux_detection_candidates")))
        center_layout.addWidget(self.result_candidates, 2)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel(get_text("mux_detection_details")))
        right_layout.addWidget(self._build_section(get_text("mux_detection_summary_section"), self.summary), 1)
        right_layout.addWidget(self._build_section(get_text("mux_detection_relationships_section"), self.relationships), 1)
        right_layout.addWidget(self._build_section(get_text("mux_detection_states_section"), self.states_table), 2)
        right_layout.addWidget(self._build_section(get_text("mux_detection_state_periods_section"), self.periods_table), 2)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        self.setCentralWidget(splitter)

    def _wire(self) -> None:
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_select_none.clicked.connect(self._select_none)
        self.btn_analyze.clicked.connect(self._analyze)
        self.result_groups.currentRowChanged.connect(self._on_group_changed)
        self.result_candidates.currentRowChanged.connect(self._on_candidate_changed)
        self.strictness.valueChanged.connect(self._on_strictness_changed)
        self.chk_hide_without_candidates.toggled.connect(self._refresh_results_view)

        self._vm.available_signals_changed.connect(self._set_signals)
        self._vm.results_changed.connect(self._set_results)
        self._vm.analysis_started.connect(self._on_analysis_started)
        self._vm.analysis_finished.connect(self._hide_progress)
        self._vm.analysis_failed.connect(self._set_error)

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

    def _analyze(self) -> None:
        selected_groups = []
        for row in range(self.signal_list.count()):
            item = self.signal_list.item(row)
            if item and item.checkState() == Qt.Checked:
                selected_groups.append(item.data(Qt.UserRole))
        self._vm.start_analysis(selected_groups=selected_groups, options=self._options())

    def _options(self) -> dict[str, bool]:
        return {
            "use_change_rate": self.chk_change_rate.isChecked(),
            "use_unique_ratio": self.chk_unique_ratio.isChecked(),
            "use_periodicity": self.chk_periodicity.isChecked(),
            "use_nmi": self.chk_nmi.isChecked(),
            "use_entropy": self.chk_entropy.isChecked(),
            "use_window_entropy": self.chk_window_entropy.isChecked(),
            "enable_bitfields": self.chk_bitfields.isChecked(),
            "require_early_state_presence": self.chk_early_state_presence.isChecked(),
            "strictness": self.strictness.value(),
        }

    def _set_results(self, results: list[dict]) -> None:
        self._results = results
        self._refresh_results_view()

    def _refresh_results_view(self) -> None:
        self.result_groups.blockSignals(True)
        self.result_groups.clear()
        results = self._visible_results()
        for result in results:
            text = f"{result['label']} ({len(result['candidates'])})"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, result)
            self.result_groups.addItem(item)
        self.result_groups.blockSignals(False)
        self.result_candidates.clear()
        self._clear_detail_sections()
        if results:
            self.result_groups.setCurrentRow(0)

    def _on_group_changed(self, row: int) -> None:
        self.result_candidates.blockSignals(True)
        self.result_candidates.clear()
        self._clear_detail_sections()
        if row < 0 or row >= self.result_groups.count():
            self.result_candidates.blockSignals(False)
            return
        group = self.result_groups.item(row).data(Qt.UserRole)
        for candidate in group.get("candidates", []):
            item = QListWidgetItem(candidate["spec"]["label"])
            item.setData(Qt.UserRole, candidate)
            self.result_candidates.addItem(item)
        self.result_candidates.blockSignals(False)
        if self.result_candidates.count() > 0:
            self.result_candidates.setCurrentRow(0)

    def _on_candidate_changed(self, row: int) -> None:
        if row < 0 or row >= self.result_candidates.count():
            self._clear_detail_sections()
            return
        candidate = self.result_candidates.item(row).data(Qt.UserRole)
        all_states = candidate.get("all_states") or candidate.get("top_values", [])
        periods = candidate.get("value_periods", {})
        dependent = ", ".join(
            f"D{byte}:{score:.2f}" for byte, score in candidate.get("most_mux_dependent_bytes", [])
        )
        other_bytes = ", ".join(
            f"D{int(stat['byte'])} ent={stat['entropy']:.2f} change={stat['change_rate']:.3f}"
            for stat in candidate.get("other_bytes_stats", [])
        )
        summary_lines = [
            f"Spec: {candidate['spec']['label']}",
            f"Score: {candidate['score']:.3f}",
            f"Probability: {candidate['probability']:.3f}",
            f"Changes: {candidate['changes']}",
            f"Change rate: {candidate['change_rate']:.4f}",
            f"Unique values: {candidate['unique_values']}",
            f"Top ratio: {candidate['top_ratio']:.3f}",
            f"Entropy: {candidate['entropy']:.3f}",
            f"Period factor: {candidate['period_factor']:.3f}",
            f"Regularity: {candidate['regularity_factor']:.3f}",
            f"NMI mean: {candidate['nmi_mean']:.3f}",
            f"NMI max: {candidate['nmi_max']:.3f}",
            f"State presence factor: {candidate.get('state_presence_factor', 1.0):.3f}",
            f"Late state fraction: {candidate.get('late_state_fraction', 0.0):.3f}",
        ]
        relationship_lines = [
            f"Most dependent bytes: {dependent or '-'}",
            f"Other varying bytes: {other_bytes or '-'}",
            f"State first-seen offsets: {self._format_state_first_seen(candidate.get('state_first_seen_normalized', {}))}",
        ]
        self.summary.setPlainText("\n".join(summary_lines))
        self.relationships.setPlainText("\n".join(relationship_lines))
        self._set_states_table(all_states)
        self._set_periods_table(periods)

    def _set_error(self, message: str) -> None:
        self._clear_detail_sections()
        self.summary.setPlainText(message)

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

    def _on_strictness_changed(self, value: int) -> None:
        self.strictness_value.setText(str(int(value)))

    def _on_analysis_started(self) -> None:
        self._show_progress(get_text("mux_detection_loading"))

    def _build_section(self, title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title, self)
        layout = QVBoxLayout(box)
        layout.addWidget(widget)
        return box

    def _clear_detail_sections(self) -> None:
        self.summary.clear()
        self.relationships.clear()
        self.states_table.setRowCount(0)
        self.periods_table.setRowCount(0)

    def _set_states_table(self, states: list[tuple[str, int]]) -> None:
        self.states_table.setRowCount(0)
        for row, (value, count) in enumerate(states):
            self.states_table.insertRow(row)
            self.states_table.setItem(row, 0, QTableWidgetItem(str(value)))
            self.states_table.setItem(row, 1, QTableWidgetItem(str(count)))
        self.states_table.resizeColumnsToContents()

    def _set_periods_table(self, periods: dict[int, dict[str, float]]) -> None:
        self.periods_table.setRowCount(0)
        for row, (value, stats) in enumerate(sorted(periods.items(), key=lambda item: item[0])):
            self.periods_table.insertRow(row)
            self.periods_table.setItem(row, 0, QTableWidgetItem(hex(int(value))))
            self.periods_table.setItem(row, 1, QTableWidgetItem(f"{stats['median_period']:.6f}"))
            self.periods_table.setItem(row, 2, QTableWidgetItem(f"{stats['mean_period']:.6f}"))
            self.periods_table.setItem(row, 3, QTableWidgetItem(f"{stats['cv']:.3f}"))
        self.periods_table.resizeColumnsToContents()

    def _visible_results(self) -> list[dict]:
        if not self.chk_hide_without_candidates.isChecked():
            return list(self._results)
        return [result for result in self._results if result.get("candidates")]

    def _format_state_first_seen(self, offsets: dict[str, float]) -> str:
        if not offsets:
            return "-"
        parts = [f"{state}:{offset:.3f}" for state, offset in offsets.items()]
        return ", ".join(parts)

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
