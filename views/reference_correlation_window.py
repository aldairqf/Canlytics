from __future__ import annotations

from pathlib import Path
from typing import Callable

import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_option, get_text
from models.analysis_context import AnalysisContext
from services.reference_correlation import (
    CorrelationResult,
    ReferenceSource,
    TimedSeries,
)
from services.candidate_interpretations import CandidateItem
from viewmodels.candidate_interpretations_viewmodel import CandidateInterpretationsViewModel
from viewmodels.event_markers_viewmodel import EventMarkersViewModel
from viewmodels.reference_correlation_viewmodel import ReferenceCorrelationViewModel
from views.widgets.eta_progress_dialog import EtaProgressDialog


class ReferenceCorrelationWindow(QDialog):
    _SOURCE_KINDS = ("csv", "dbc", "candidate", "markers")

    def __init__(
        self,
        vm: ReferenceCorrelationViewModel,
        candidate: CandidateItem,
        *,
        dataframe_getter: Callable[[], pl.DataFrame],
        candidates_vm: CandidateInterpretationsViewModel,
        markers_vm: EventMarkersViewModel,
        analysis_context_vm,
        dbc_signal_options_getter: Callable[[], tuple[tuple[str, str, str], ...]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("reference_correlation_title"))
        self.resize(780, 560)
        self._vm = vm
        self._candidate = candidate
        self._dataframe_getter = dataframe_getter
        self._candidates_vm = candidates_vm
        self._markers_vm = markers_vm
        self._analysis_context_vm = analysis_context_vm
        self._dbc_signal_options_getter = dbc_signal_options_getter
        self._progress: EtaProgressDialog | None = None
        self._result: CorrelationResult | None = None
        self._reference: TimedSeries | None = None

        layout = QVBoxLayout(self)
        self._candidate_label = QLabel(self)
        self._candidate_label.setWordWrap(True)
        layout.addWidget(self._candidate_label)
        form = QFormLayout()
        layout.addLayout(form)
        self._source = QComboBox(self)
        for kind, key in zip(self._SOURCE_KINDS, (
            "reference_correlation_source_csv",
            "reference_correlation_source_dbc",
            "reference_correlation_source_candidate",
            "reference_correlation_source_markers",
        )):
            self._source.addItem(get_text(key), kind)
        form.addRow(get_text("reference_correlation_reference"), self._source)
        self._source_stack = QStackedWidget(self)
        self._csv_page = self._build_csv_page()
        self._dbc_page = self._build_dbc_page()
        self._candidate_page = self._build_candidate_page()
        self._markers_page = self._build_markers_page()
        for page in (self._csv_page, self._dbc_page, self._candidate_page, self._markers_page):
            self._source_stack.addWidget(page)
        form.addRow(self._source_stack)
        self._method = QComboBox(self)
        self._method.addItem("Spearman", "spearman")
        self._method.addItem("Pearson", "pearson")
        self._method.setCurrentIndex(
            max(0, self._method.findData(str(get_option("reference_correlation_method", "spearman"))))
        )
        form.addRow(get_text("reference_correlation_method"), self._method)
        self._window_seconds = self._spin(
            float(get_option("reference_correlation_window_seconds", 5.0)), 0.1, 3600.0, 1
        )
        form.addRow(get_text("reference_correlation_window_seconds"), self._window_seconds)
        self._max_lag = self._spin(
            float(get_option("reference_correlation_max_lag_seconds", 2.0)), 0.0, 3600.0, 2
        )
        form.addRow(get_text("reference_correlation_max_lag"), self._max_lag)
        self._lag_step = self._spin(
            float(get_option("reference_correlation_lag_step_seconds", 0.05)), 0.001, 60.0, 3
        )
        form.addRow(get_text("reference_correlation_lag_step"), self._lag_step)

        actions = QHBoxLayout()
        self._run = QPushButton(get_text("reference_correlation_run"), self)
        self._save = QPushButton(get_text("reference_correlation_save_signal"), self)
        self._save.setEnabled(False)
        actions.addWidget(self._run)
        actions.addWidget(self._save)
        actions.addStretch(1)
        layout.addLayout(actions)
        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._windows = QTableWidget(0, 4, self)
        self._windows.setHorizontalHeaderLabels([
            get_text("reference_correlation_window_start"),
            get_text("reference_correlation_window_end"),
            get_text("reference_correlation_coefficient"),
            get_text("reference_correlation_samples"),
        ])
        self._windows.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._windows, 1)

        self._source.currentIndexChanged.connect(self._update_source_page)
        self._run.clicked.connect(self._run_analysis)
        self._save.clicked.connect(self._save_as_signal)
        self._vm.analysis_started.connect(self._on_analysis_started)
        self._vm.analysis_progress.connect(self._report_progress)
        self._vm.analysis_finished.connect(self._on_analysis_finished)
        self._vm.analysis_failed.connect(self._on_analysis_failed)
        self._vm.analysis_canceled.connect(self._on_analysis_canceled)
        self._update_candidate_label()
        self._update_source_page()

    @staticmethod
    def _spin(value: float, minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        return spin

    def set_candidate(self, candidate: CandidateItem) -> None:
        if self._vm.running:
            return
        self._candidate = candidate
        self._result = None
        self._reference = None
        self._save.setEnabled(False)
        self._update_candidate_label()

    def _update_candidate_label(self) -> None:
        self._candidate_label.setText(get_text("reference_correlation_candidate").format(
            label=self._candidate.label,
            can_id=self._candidate.can_id,
            start_bit=self._candidate.start_bit,
            length=self._candidate.signal_length,
        ))

    def _build_csv_page(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        self._csv_path = QLabel(get_text("reference_correlation_no_file"), page)
        self._csv_path.setWordWrap(True)
        self._csv_path.setToolTip(get_text("reference_correlation_csv_help"))
        self._csv_browse = QPushButton(get_text("reference_correlation_browse"), page)
        self._csv_browse.clicked.connect(self._browse_csv)
        layout.addWidget(self._csv_path, 1)
        layout.addWidget(self._csv_browse)
        return page

    def _build_dbc_page(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        self._dbc_signal = QComboBox(page)
        self._dbc_signal.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for data in self._dbc_signal_options_getter():
            self._dbc_signal.addItem(" · ".join(data), data)
        layout.addWidget(self._dbc_signal)
        return page

    def _build_candidate_page(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        self._other_candidate = QComboBox(page)
        for candidate in self._candidates_vm.candidate_items:
            if candidate.label != self._candidate.label:
                self._other_candidate.addItem(candidate.label, candidate.label)
        layout.addWidget(self._other_candidate)
        return page

    def _build_markers_page(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        self._marker_name = QComboBox(page)
        self._marker_name.addItems(sorted({str(marker["name"]) for marker in self._markers_vm.context_markers()}))
        layout.addWidget(self._marker_name)
        return page

    def _browse_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, get_text("reference_correlation_csv_title"), "", "CSV (*.csv);;All files (*)")
        if path:
            self._csv_path.setText(path)

    def _update_source_page(self, *_args) -> None:
        kind = self._source.currentData()
        self._source_stack.setCurrentIndex(self._SOURCE_KINDS.index(kind))
        self._run.setEnabled(self._vm is not None and not self._vm.running)

    def _selected_reference(self) -> ReferenceSource:
        kind = str(self._source.currentData())
        if kind == "csv":
            path = self._csv_path.text()
            if path == get_text("reference_correlation_no_file") or not Path(path).is_file():
                raise ValueError(get_text("reference_correlation_select_csv"))
            return ReferenceSource(kind="csv", name=Path(path).stem, path=path)
        if kind == "dbc":
            data = self._dbc_signal.currentData()
            if not data:
                raise ValueError(get_text("reference_correlation_select_dbc"))
            dbc_name, message_name, signal_name = data
            return ReferenceSource(
                kind="dbc", name=str(signal_name), dbc_name=str(dbc_name),
                message_name=str(message_name), signal_name=str(signal_name),
            )
        if kind == "candidate":
            label = self._other_candidate.currentData()
            if not label:
                raise ValueError(get_text("reference_correlation_select_candidate"))
            return ReferenceSource(kind="candidate", name=str(label), candidate_label=str(label))
        name = self._marker_name.currentText().strip()
        if not name:
            raise ValueError(get_text("reference_correlation_select_marker"))
        return ReferenceSource(kind="markers", name=name)

    def _run_analysis(self) -> None:
        try:
            source = self._selected_reference()
            self._vm.analyze(
                TimedSeries(self._candidate.label, self._candidate.timestamps, self._candidate.values),
                source,
                dataframe=self._dataframe_getter(),
                candidates=tuple(self._candidates_vm.candidate_items),
                markers=self._markers_vm.context_markers(),
                method=str(self._method.currentData()),
                window_seconds=self._window_seconds.value(),
                max_lag_seconds=self._max_lag.value(),
                lag_step_seconds=self._lag_step.value(),
                min_samples_per_window=int(
                    get_option("reference_correlation_min_samples_per_window", 5)
                ),
            )
        except Exception as exc:
            self._on_analysis_failed(str(exc))

    def _on_analysis_started(self) -> None:
        self._result = None
        self._save.setEnabled(False)
        self._summary.clear()
        self._progress = EtaProgressDialog(
            get_text("reference_correlation_progress"),
            get_text("common_cancel"),
            self,
        )
        self._progress.canceled.connect(self._vm.cancel)
        self._progress.start()
        self._run.setEnabled(False)

    def _report_progress(self, done: int, total: int) -> None:
        if self._progress is not None:
            self._progress.report_progress(done, total)

    def _on_analysis_finished(self, payload: tuple[CorrelationResult, TimedSeries]) -> None:
        self._close_progress()
        self._result, self._reference = payload
        result = self._result
        self._summary.setText(get_text("reference_correlation_summary").format(
            name=self._reference.name,
            coefficient=result.coefficient,
            lag=result.lag_seconds,
            scale=result.scale,
            offset=result.offset,
            samples=result.samples,
            windows=len(result.windows),
        ))
        self._windows.setRowCount(len(result.windows))
        for row, item in enumerate(result.windows):
            values = (item.start, item.end, item.coefficient, item.samples)
            for column, value in enumerate(values):
                self._windows.setItem(row, column, QTableWidgetItem(f"{value:.6g}"))
        self._save.setEnabled(True)
        self._run.setEnabled(True)

    def _on_analysis_failed(self, message: str) -> None:
        self._close_progress()
        self._summary.setText(get_text("reference_correlation_error").format(error=message))
        self._run.setEnabled(True)

    def _on_analysis_canceled(self) -> None:
        self._close_progress()
        self._summary.setText(get_text("reference_correlation_canceled"))
        self._run.setEnabled(True)

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def _save_as_signal(self) -> None:
        if self._result is None or self._analysis_context_vm is None:
            return
        context = AnalysisContext.from_signal(
            can_id=self._candidate.can_id,
            start_bit=self._candidate.start_bit,
            length=self._candidate.signal_length,
            little_endian=self._candidate.byte_order == "LittleEndian",
            mux_case=self._candidate.mux_value,
            source_window=get_text("reference_correlation_title"),
            suggested_scale=self._result.scale,
            suggested_offset=self._result.offset,
        )
        self._analysis_context_vm.send_to("working_dbc", context)

    def closeEvent(self, event) -> None:
        if self._vm.running:
            self._vm.cancel()
            self._vm.wait()
        self._close_progress()
        super().closeEvent(event)
