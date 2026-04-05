from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QProgressDialog,
    QSpinBox,
    QSplitter,
    QSlider,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg

from config.app_config import get_text
from viewmodels.candidate_interpretations_viewmodel import (
    CandidateInterpretationsViewModel,
    CandidateItem,
    CandidateSeries,
)
from views.settings.mux_configuration_dialog import MuxConfigurationDialog


class CandidateInterpretationsWindow(QMainWindow):
    def __init__(self, vm: CandidateInterpretationsViewModel, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("candidate_interpretations_title"))
        self.resize(1550, 920)
        self._vm = vm
        self._legend = None
        self._build_ui()
        self._wire()
        self._apply_parameters()
        self._vm.set_dataframe(getattr(self._vm, "_df", None))

    def _build_ui(self) -> None:
        self.can_ids = QListWidget(self)
        self.can_ids.setMinimumWidth(240)
        self.can_ids.setSelectionMode(QAbstractItemView.NoSelection)

        self.btn_select_all = QPushButton(get_text("select_all"), self)
        self.btn_select_none = QPushButton(get_text("select_none"), self)
        self.btn_mux = QPushButton(get_text("mux_configuration_button"), self)
        self._recalc_dialog: QProgressDialog | None = None

        self.min_length = QSpinBox(self)
        self.min_length.setRange(1, 64)
        self.min_length.setValue(8)

        self.max_length = QSpinBox(self)
        self.max_length.setRange(1, 64)
        self.max_length.setValue(8)

        self.granularity = QSpinBox(self)
        self.granularity.setRange(1, 64)
        self.granularity.setValue(8)

        self.endianness = QComboBox(self)
        self.endianness.addItems(
            [
                get_text("candidate_interpretations_try_both"),
                get_text("candidate_interpretations_little_endian"),
                get_text("candidate_interpretations_big_endian"),
            ]
        )

        self.value_type = QComboBox(self)
        self.value_type.addItems(
            [
                get_text("candidate_interpretations_try_all"),
                get_text("candidate_interpretations_unsigned"),
                get_text("candidate_interpretations_signed"),
                get_text("candidate_interpretations_float32"),
            ]
        )

        self.sensitivity = QSlider(Qt.Horizontal, self)
        self.sensitivity.setRange(0, 100)
        self.sensitivity.setValue(50)
        self.sensitivity_value = QLabel("50", self)

        form = QFormLayout()
        form.addRow(get_text("candidate_interpretations_min_length"), self.min_length)
        form.addRow(get_text("candidate_interpretations_max_length"), self.max_length)
        form.addRow(get_text("candidate_interpretations_granularity"), self.granularity)
        form.addRow(get_text("candidate_interpretations_endianness"), self.endianness)
        form.addRow(get_text("candidate_interpretations_value_type"), self.value_type)

        sensitivity_row = QVBoxLayout()
        sensitivity_row.addWidget(self.sensitivity)
        sensitivity_labels = QHBoxLayout()
        sensitivity_labels.addWidget(QLabel(get_text("candidate_interpretations_sensitivity_low")))
        sensitivity_labels.addStretch(1)
        sensitivity_labels.addWidget(self.sensitivity_value)
        sensitivity_labels.addStretch(1)
        sensitivity_labels.addWidget(QLabel(get_text("candidate_interpretations_sensitivity_high")))
        sensitivity_row.addLayout(sensitivity_labels)
        form.addRow(get_text("candidate_interpretations_sensitivity"), sensitivity_row)

        self.btn_recalculate = QPushButton(get_text("candidate_interpretations_recalculate"), self)

        left_top_buttons = QHBoxLayout()
        left_top_buttons.addWidget(self.btn_select_all)
        left_top_buttons.addWidget(self.btn_select_none)

        mux_row = QHBoxLayout()
        mux_row.addWidget(QLabel(get_text("mux_configuration_label")))
        mux_row.addWidget(self.btn_mux)
        mux_row.addStretch(1)

        controls = QWidget(self)
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(QLabel(get_text("candidate_interpretations_parameters")))
        controls_layout.addLayout(form)
        controls_layout.addWidget(self.btn_recalculate)
        controls_layout.addStretch(1)

        self.candidate_list = QListWidget(self)
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel(get_text("candidate_interpretations_can_ids")))
        left_layout.addLayout(left_top_buttons)
        left_layout.addWidget(self.can_ids, 1)
        left_layout.addLayout(mux_row)
        left_layout.addWidget(controls)
        left_layout.addWidget(QLabel(get_text("candidate_interpretations_candidates")))
        left_layout.addWidget(self.candidate_list, 2)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)

        self.plot = pg.PlotWidget(self)
        self._legend = self.plot.addLegend(offset=(10, 10))
        self.plot.setLabel("bottom", "Time")
        self.plot.setLabel("left", "Decoded Value")
        self.plot.showGrid(x=True, y=True, alpha=0.25)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel(get_text("candidate_interpretations_details")))
        right_layout.addWidget(self.details)
        right_layout.addWidget(self.plot, 1)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _wire(self) -> None:
        self.btn_select_all.clicked.connect(self._select_all_ids)
        self.btn_select_none.clicked.connect(self._select_none_ids)
        self.btn_mux.clicked.connect(self._open_mux_dialog)
        self.btn_recalculate.clicked.connect(self._recalculate)
        self.candidate_list.currentRowChanged.connect(self._vm.set_selected_candidate_index)
        self.sensitivity.valueChanged.connect(self._on_sensitivity_changed)

        self._vm.can_ids_changed.connect(self._set_can_ids)
        self._vm.candidate_list_changed.connect(self._set_candidate_list)
        self._vm.candidate_detail_changed.connect(self._set_details)
        self._vm.candidate_plot_changed.connect(self._set_plot_data)

    def _open_mux_dialog(self) -> None:
        dlg = MuxConfigurationDialog(self._vm.mux_configs, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._vm.set_mux_configuration(dlg.configs())

    def _apply_parameters(self) -> None:
        self._vm.set_parameters(
            min_length=self.min_length.value(),
            max_length=self.max_length.value(),
            granularity=self.granularity.value(),
            endianness=self.endianness.currentText(),
            value_type=self.value_type.currentText(),
            sensitivity=self.sensitivity.value(),
        )

    def _recalculate(self) -> None:
        self._run_recalculate(get_text("candidate_interpretations_recalculating"))

    def _set_can_ids(self, ids: list[str]) -> None:
        self.can_ids.blockSignals(True)
        self.can_ids.clear()
        for can_id in ids:
            item = QListWidgetItem(can_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
            self.can_ids.addItem(item)
        self.can_ids.blockSignals(False)

    def _checked_ids(self) -> set[str]:
        checked: set[str] = set()
        for row in range(self.can_ids.count()):
            item = self.can_ids.item(row)
            if item and item.checkState() == Qt.Checked:
                checked.add(item.text().strip().upper())
        return checked

    def _select_all_ids(self) -> None:
        self.can_ids.blockSignals(True)
        for row in range(self.can_ids.count()):
            item = self.can_ids.item(row)
            if item:
                item.setCheckState(Qt.Checked)
        self.can_ids.blockSignals(False)

    def _select_none_ids(self) -> None:
        self.can_ids.blockSignals(True)
        for row in range(self.can_ids.count()):
            item = self.can_ids.item(row)
            if item:
                item.setCheckState(Qt.Unchecked)
        self.can_ids.blockSignals(False)
        self._run_recalculate(get_text("candidate_interpretations_recalculating"))

    def _set_candidate_list(self, items: list[CandidateItem]) -> None:
        current_row = self.candidate_list.currentRow()
        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        for item in items:
            self.candidate_list.addItem(item.label)
        self.candidate_list.blockSignals(False)
        if not items:
            return
        row = current_row if 0 <= current_row < len(items) else 0
        self.candidate_list.setCurrentRow(row)
        self._vm.set_selected_candidate_index(row)

    def _set_details(self, details: dict) -> None:
        if not details:
            self.details.clear()
            return
        self.details.setPlainText("\n".join(f"{key}: {value}" for key, value in details.items()))

    def _set_plot_data(self, series: list[CandidateSeries]) -> None:
        self.plot.clear()
        if self._legend is None:
            self._legend = self.plot.addLegend(offset=(10, 10))
        for item in series:
            self.plot.plot(item.x, item.y, pen=pg.mkPen(item.color, width=1.8), name=item.label)
        self.plot.enableAutoRange()
        self.plot.autoRange()

    def _on_sensitivity_changed(self, value: int) -> None:
        self.sensitivity_value.setText(str(int(value)))

    def _run_recalculate(self, message: str) -> None:
        self._apply_parameters()
        self._vm.set_checked_ids(self._checked_ids())
        self._show_recalc_dialog(message)
        try:
            self._vm.recalculate()
        finally:
            self._hide_recalc_dialog()

    def _show_recalc_dialog(self, message: str) -> None:
        self._recalc_dialog = QProgressDialog(message, "", 0, 0, self)
        self._recalc_dialog.setWindowTitle(get_text("candidate_interpretations_title"))
        self._recalc_dialog.setCancelButton(None)
        self._recalc_dialog.setWindowModality(Qt.ApplicationModal)
        self._recalc_dialog.show()
        QApplication.processEvents()

    def _hide_recalc_dialog(self) -> None:
        if self._recalc_dialog is not None:
            self._recalc_dialog.close()
            self._recalc_dialog = None
