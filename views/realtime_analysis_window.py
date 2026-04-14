from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.defaults import REAL_TIME_ANALYSIS_COLUMNS
from config.app_config import get_text
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.real_time_analysis_viewmodel import RealTimeAnalysisViewModel
from viewmodels.table_filter_viewmodel import TableFilterViewModel
from viewmodels.table_model import TableModel
from viewmodels.table_viewmodel import TableViewModel
from views.settings.mux_configuration_dialog import MuxConfigurationDialog
from views.table.row_height_manager import RowHeightManager
from views.table.data_bytes_highlight_delegate import DataBytesHighlightDelegate
from views.table.table_view import DataTableView
from views.widgets.can_id_panel import CanIdPanelWidget


class RealTimeAnalysisWindow(QMainWindow):
    def __init__(self, analysis_vm: RealTimeAnalysisViewModel, dbc_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(get_text("real_time_analysis_label"))
        self.resize(1100, 700)

        self._analysis_vm = analysis_vm
        self._filter_vm = TableFilterViewModel()
        self._filter_vm.set_real_time_analysis(True)

        self._table_model = TableModel(REAL_TIME_ANALYSIS_COLUMNS, optimize_append=False)
        self._table_vm = TableViewModel(self._table_model)
        self._interpret_vm = InterpretationViewModel(dbc_manager, self._table_vm, parent=self)
        self._data_delegate = DataBytesHighlightDelegate(self)

        self.table = DataTableView(self._table_model)
        self.table.setItemDelegateForColumn(REAL_TIME_ANALYSIS_COLUMNS.index("DATA"), self._data_delegate)
        self.panel = CanIdPanelWidget(dbc_manager, self._interpret_vm, parent=self)
        self.row_heights = RowHeightManager(self.table, self._table_model, self._table_vm)

        self.show_only_changing = QCheckBox(get_text("show_only_changing_label"))
        self.show_only_changing.setChecked(self._analysis_vm.show_only_changing)
        self.detect_changes = QCheckBox(get_text("real_time_detect_changes_label"))
        self.detect_changes.setChecked(self._analysis_vm.detect_changes)
        self.show_bits = QCheckBox(get_text("real_time_show_bits_label"))
        self.show_bits.setChecked(False)
        self.refresh_interval = QSpinBox(self)
        self.refresh_interval.setRange(25, 5000)
        self.refresh_interval.setSingleStep(25)
        self.refresh_interval.setSuffix(" ms")
        self.refresh_interval.setValue(self._analysis_vm.refresh_interval_ms)
        self.mux_summary = QLabel(self._analysis_vm.mux_configuration_summary())
        self.btn_mux_configuration = QPushButton(get_text("mux_configuration_button"))
        self.btn_reset = QPushButton(get_text("reset_change_detection"))
        self.status = QLabel(get_text("connection_status_idle"))

        controls = QWidget(self)
        controls_layout = QHBoxLayout(controls)
        controls_layout.addWidget(QLabel(get_text("real_time_detect_changes_mode_label")))
        controls_layout.addWidget(self.detect_changes)
        controls_layout.addWidget(QLabel(get_text("show_only_changing_mode_label")))
        controls_layout.addWidget(self.show_only_changing)
        controls_layout.addWidget(QLabel(get_text("real_time_data_format_mode_label")))
        controls_layout.addWidget(self.show_bits)
        controls_layout.addWidget(QLabel(get_text("real_time_refresh_interval_label")))
        controls_layout.addWidget(self.refresh_interval)
        controls_layout.addWidget(QLabel(get_text("mux_configuration_label")))
        controls_layout.addWidget(self.mux_summary, 1)
        controls_layout.addWidget(self.btn_mux_configuration)
        controls_layout.addWidget(self.btn_reset)
        controls_layout.addWidget(self.status, 1)

        body = QWidget(self)
        body_layout = QHBoxLayout(body)
        body_layout.addWidget(self.table, 4)
        body_layout.addWidget(self.panel, 1)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(controls)
        layout.addWidget(body, 1)
        self.setCentralWidget(central)

        self._analysis_vm.dataframe_changed.connect(self._filter_vm.set_live_dataframe)
        self._filter_vm.dataframe_changed.connect(self._table_vm.set_dataframe)
        self._filter_vm.can_ids_changed.connect(self.panel.set_can_ids)
        self.panel.selected_ids_changed.connect(self._filter_vm.set_selected_ids)
        self.panel.interpret_toggled.connect(self._interpret_vm.set_enabled)
        self._interpret_vm.enabled_changed.connect(self._on_interpret_enabled_changed)
        self._interpret_vm.available_changed.connect(self.panel.set_interpret_available)
        self.panel.expand_all_clicked.connect(self.row_heights.expand_all)
        self.panel.collapse_all_clicked.connect(self.row_heights.collapse_all)

        self.detect_changes.toggled.connect(self._analysis_vm.set_detect_changes)
        self.show_only_changing.toggled.connect(self._analysis_vm.set_show_only_changing)
        self.show_bits.toggled.connect(self._on_show_bits_toggled)
        self.refresh_interval.valueChanged.connect(self._analysis_vm.set_refresh_interval_ms)
        self.btn_mux_configuration.clicked.connect(self._open_mux_configuration)
        self.btn_reset.clicked.connect(self._analysis_vm.reset_change_detection)
        self._analysis_vm.mux_configuration_changed.connect(self._refresh_mux_summary)
        self._analysis_vm.detect_changes_changed.connect(self._on_detect_changes_changed)
        self._analysis_vm.refresh_interval_changed.connect(self._on_refresh_interval_changed)
        self._analysis_vm.show_only_changing_changed.connect(self._on_show_only_changing_changed)

        self._filter_vm.set_live_dataframe(getattr(self._analysis_vm, "_df"))
        self.panel.set_interpret_available(self._interpret_vm.available)
        self._on_interpret_enabled_changed(self._interpret_vm.enabled)
        self._on_detect_changes_changed(self._analysis_vm.detect_changes)

    def _open_mux_configuration(self) -> None:
        dlg = MuxConfigurationDialog(self._analysis_vm.mux_configs, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self._analysis_vm.set_mux_configuration(dlg.configs())
            self.status.setText(get_text("connection_status_idle"))
        except ValueError as exc:
            self.status.setText(get_text("connection_error_prefix").format(error=str(exc)))
        self._refresh_mux_summary()

    def _refresh_mux_summary(self) -> None:
        self.mux_summary.setText(self._analysis_vm.mux_configuration_summary())

    def _on_interpret_enabled_changed(self, enabled: bool) -> None:
        self.panel.set_interpret_checked(enabled)
        self.panel.refresh_labels()
        self.row_heights.refresh()

    def _on_detect_changes_changed(self, enabled: bool) -> None:
        self.detect_changes.blockSignals(True)
        self.detect_changes.setChecked(enabled)
        self.detect_changes.blockSignals(False)
        self.show_only_changing.setEnabled(enabled)
        self.btn_reset.setEnabled(enabled)
        if not enabled:
            self._on_show_only_changing_changed(False)

    def _on_show_only_changing_changed(self, enabled: bool) -> None:
        self.show_only_changing.blockSignals(True)
        self.show_only_changing.setChecked(enabled)
        self.show_only_changing.blockSignals(False)

    def _on_show_bits_toggled(self, enabled: bool) -> None:
        self._table_model.set_data_display_mode("bits" if enabled else "bytes")

    def _on_refresh_interval_changed(self, interval_ms: int) -> None:
        self.refresh_interval.blockSignals(True)
        self.refresh_interval.setValue(int(interval_ms))
        self.refresh_interval.blockSignals(False)

    def closeEvent(self, event) -> None:
        self._interpret_vm.shutdown()
        super().closeEvent(event)
