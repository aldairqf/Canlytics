from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
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
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.settings.mux_configuration_dialog import MuxConfigurationDialog
from views.table.row_height_manager import RowHeightManager
from views.table.data_bytes_highlight_delegate import DataBytesHighlightDelegate
from views.table.table_view import DataTableView
from views.widgets.can_id_panel import CanIdPanelWidget


class RealTimeAnalysisWindow(QMainWindow):
    def __init__(
        self,
        analysis_vm: RealTimeAnalysisViewModel,
        dbc_manager,
        time_config_vm: TimeConfigViewModel,
        parent=None,
    ):
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
        self.panel = CanIdPanelWidget(
            dbc_manager.resolve_message_name,
            self._interpret_vm,
            time_config_vm,
            show_time_filter=False,
            show_interpret_controls=False,
            parent=self,
        )
        self.row_heights = RowHeightManager(self.table, self._table_model, self._table_vm)
        self._selected_ids: set[str] = set()
        self._details_can_id: str | None = None
        self._details_row: dict | None = None
        self._details_signature: str = ""

        self.show_only_changing = QCheckBox(get_text("show_only_changing_label"))
        self.show_only_changing.setChecked(self._analysis_vm.show_only_changing)
        self.detect_changes = QCheckBox(get_text("real_time_detect_changes_label"))
        self.detect_changes.setChecked(self._analysis_vm.detect_changes)
        self.detect_changes.setText("Track Changes")
        self.show_only_changing.setText("Changes Only")
        self.show_only_changing.setToolTip("Show only IDs that have changed since the last reset.")
        self.show_bits = QCheckBox(get_text("real_time_show_bits_label"))
        self.show_bits.setChecked(False)
        self.show_bits.setText("Show Bits")
        self.refresh_interval = QSpinBox(self)
        self.refresh_interval.setRange(10, 5000)
        self.refresh_interval.setSingleStep(10)
        self.refresh_interval.setSuffix(" ms")
        self.refresh_interval.setValue(self._analysis_vm.refresh_interval_ms)
        self.highlight_hold = QSpinBox(self)
        self.highlight_hold.setRange(100, 10000)
        self.highlight_hold.setSingleStep(100)
        self.highlight_hold.setSuffix(" ms")
        self.highlight_hold.setValue(self._analysis_vm.highlight_hold_ms)
        self.mux_summary = QLabel(self._analysis_vm.mux_configuration_summary())
        self.change_summary = QLabel("")
        self.btn_mux_configuration = QPushButton(get_text("mux_configuration_button"))
        self.btn_reset = QPushButton(get_text("reset_change_detection"))
        self.btn_reset.setText("Reset Realtime")
        self.status = QLabel(get_text("connection_status_idle"))
        self.details_card = QFrame(self)
        self.details_card.setFrameShape(QFrame.StyledPanel)
        self.details_id = QLabel("ID -", self.details_card)
        self.details_subtitle = QLabel("", self.details_card)
        self.details_frame = QLabel("", self.details_card)
        self.details_unique = self._make_details_table(self.details_card)
        card_layout = QVBoxLayout(self.details_card)
        card_layout.addWidget(self.details_id)
        card_layout.addWidget(self.details_subtitle)
        card_layout.addWidget(self.details_frame)
        card_layout.addWidget(QLabel("Unique values per byte", self.details_card))
        card_layout.addWidget(self.details_unique)

        controls = QWidget(self)
        controls_layout = QHBoxLayout(controls)
        controls_layout.addWidget(self.detect_changes)
        controls_layout.addWidget(self.show_only_changing)
        controls_layout.addWidget(self.btn_reset)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.show_bits)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(QLabel(get_text("real_time_refresh_interval_label")))
        controls_layout.addWidget(self.refresh_interval)
        controls_layout.addWidget(QLabel("Highlight Hold"))
        controls_layout.addWidget(self.highlight_hold)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.btn_mux_configuration)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.change_summary)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.mux_summary)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.status, 1)

        body = QSplitter(self)
        body.setOrientation(Qt.Horizontal)
        side = QWidget(self)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(QLabel("Details"))
        side_layout.addWidget(self.details_card, 2)
        side_layout.addWidget(self.panel, 3)
        body.addWidget(self.table)
        body.addWidget(side)
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 1)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(controls)
        layout.addWidget(body, 1)
        self.setCentralWidget(central)
        self._hide_realtime_columns()

        self._analysis_vm.dataframe_changed.connect(self._filter_vm.set_live_dataframe)
        self._analysis_vm.dataframe_changed.connect(lambda _df: self._refresh_details())
        self._filter_vm.dataframe_changed.connect(self._table_vm.set_dataframe)
        self._filter_vm.can_ids_changed.connect(self.panel.set_can_ids)
        self.panel.selected_ids_changed.connect(self._on_selected_ids_changed)
        self.table.pressed.connect(self._on_table_interaction)
        self.table.clicked.connect(self._on_table_interaction)

        self.detect_changes.toggled.connect(self._analysis_vm.set_detect_changes)
        self.show_only_changing.toggled.connect(self._analysis_vm.set_show_only_changing)
        self.show_bits.toggled.connect(self._on_show_bits_toggled)
        self.refresh_interval.valueChanged.connect(self._analysis_vm.set_refresh_interval_ms)
        self.highlight_hold.valueChanged.connect(self._analysis_vm.set_highlight_hold_ms)
        self.btn_mux_configuration.clicked.connect(self._open_mux_configuration)
        self.btn_reset.clicked.connect(self._analysis_vm.reset_realtime_state)
        self._analysis_vm.mux_configuration_changed.connect(self._refresh_mux_summary)
        self._analysis_vm.change_summary_changed.connect(self.change_summary.setText)
        self._analysis_vm.detect_changes_changed.connect(self._on_detect_changes_changed)
        self._analysis_vm.refresh_interval_changed.connect(self._on_refresh_interval_changed)
        self._analysis_vm.highlight_hold_changed.connect(self._on_highlight_hold_changed)
        self._analysis_vm.show_only_changing_changed.connect(self._on_show_only_changing_changed)

        self._filter_vm.set_live_dataframe(getattr(self._analysis_vm, "_df"))
        self._on_detect_changes_changed(self._analysis_vm.detect_changes)
        self.change_summary.setText("Change detection OFF")
        self._refresh_details()

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
        self.show_only_changing.setToolTip(
            "Show only IDs that have changed since the last reset."
            if enabled
            else "Requires Track Changes."
        )
        if not enabled:
            self._on_show_only_changing_changed(False)

    def _on_show_only_changing_changed(self, enabled: bool) -> None:
        self.show_only_changing.blockSignals(True)
        self.show_only_changing.setChecked(enabled)
        self.show_only_changing.blockSignals(False)

    def _on_show_bits_toggled(self, enabled: bool) -> None:
        self._table_model.set_data_display_mode("bits" if enabled else "bytes")

    def _on_selected_ids_changed(self, ids: set[str]) -> None:
        selected = {str(v).strip().upper() for v in (ids or set()) if str(v).strip()}
        self._selected_ids = selected
        self._filter_vm.set_selected_ids(selected)
        self._refresh_details()

    def _on_table_interaction(self, index) -> None:
        if not index.isValid():
            return
        row_record = self._table_model.get_row_record(index.row())
        self._details_row = dict(row_record) if isinstance(row_record, dict) else None
        can_id = self._table_model.get_row_can_id(index.row())
        self._details_can_id = (str(can_id).strip().upper() if can_id is not None else None)
        self._refresh_details()

    def _refresh_details(self) -> None:
        data = None
        if self._details_row:
            data = self._analysis_vm.details_data_for_row(self._details_row)
        elif self._details_can_id:
            data = self._analysis_vm.details_data_for_selection([self._details_can_id])
        else:
            data = self._analysis_vm.details_data_for_selection(self._selected_ids)
        signature = repr(data)
        if signature == self._details_signature:
            return
        self._details_signature = signature
        self._render_details(data)

    def _render_details(self, data: dict) -> None:
        if data.get("empty"):
            self.details_id.setText("ID -")
            self.details_subtitle.setText(data.get("empty", ""))
            self.details_frame.setText("")
            self._fill_details_table(self.details_unique, ["-"] * 8)
            return

        self.details_id.setText(f"ID {data.get('id', '-')}")
        self.details_subtitle.setText(str(data.get("subtitle", "") or ""))
        frame = data.get("frame", {})
        self.details_frame.setText(
            f"Period [s]  min: {frame.get('min', '-')}   max: {frame.get('max', '-')}   "
            f"avg: {frame.get('avg', '-')}   n: {frame.get('n', '-')}"
        )
        self._fill_details_table(self.details_unique, list(data.get("unique", ["-"] * 8)))

    def _make_details_table(self, parent: QWidget) -> QTableWidget:
        table = QTableWidget(2, 8, parent)
        table.setHorizontalHeaderLabels([f"B{i}" for i in range(8)])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFixedHeight(84)
        return table

    def _hide_realtime_columns(self) -> None:
        for name in ("Delta T", "Bus"):
            if name not in self._table_model._columns:
                continue
            col = self._table_model._columns.index(name)
            self.table.setColumnHidden(col, True)

    def _fill_details_table(self, table: QTableWidget, values: list[str]) -> None:
        table.blockSignals(True)
        for col in range(8):
            table.setItem(0, col, QTableWidgetItem(f"B{col}"))
            table.setItem(1, col, QTableWidgetItem(str(values[col] if col < len(values) else "-")))
        table.blockSignals(False)

    def _on_refresh_interval_changed(self, interval_ms: int) -> None:
        self.refresh_interval.blockSignals(True)
        self.refresh_interval.setValue(int(interval_ms))
        self.refresh_interval.blockSignals(False)

    def _on_highlight_hold_changed(self, hold_ms: int) -> None:
        self.highlight_hold.blockSignals(True)
        self.highlight_hold.setValue(int(hold_ms))
        self.highlight_hold.blockSignals(False)

    def closeEvent(self, event) -> None:
        self._interpret_vm.shutdown()
        super().closeEvent(event)
