from __future__ import annotations

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from models.j1939 import J1939AnalysisSnapshot
from viewmodels.j1939_monitor_viewmodel import J1939MonitorViewModel
from views.widgets.eta_progress_dialog import EtaProgressDialog


class J1939MonitorWindow(QMainWindow):
    refresh_requested = QtSignal()

    def __init__(self, vm: J1939MonitorViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("j1939_monitor_title"))
        self.resize(1000, 620)
        self._vm = vm
        self._progress: EtaProgressDialog | None = None
        body = QWidget(self)
        layout = QVBoxLayout(body)
        header = QHBoxLayout()
        self._status = QLabel(get_text("j1939_monitor_ready"), body)
        self._status.setWordWrap(True)
        header.addWidget(self._status, 1)
        self._refresh = QPushButton(get_text("j1939_monitor_refresh"), body)
        self._refresh.clicked.connect(self.refresh_requested)
        header.addWidget(self._refresh)
        layout.addLayout(header)
        self._tabs = QTabWidget(body)
        self._nodes = self._make_table(
            ["j1939_node_sa", "j1939_node_name", "j1939_node_manufacturer", "j1939_node_function", "j1939_node_seen", "j1939_node_claimed"]
        )
        self._dtcs = self._make_table(
            ["j1939_dtc_sa", "j1939_dtc_pgn", "j1939_dtc_spn", "j1939_dtc_fmi", "j1939_dtc_occurrences", "j1939_dtc_lamps", "j1939_dtc_seen"]
        )
        self._tabs.addTab(self._nodes, get_text("j1939_monitor_nodes"))
        self._tabs.addTab(self._dtcs, get_text("j1939_monitor_dm1"))
        layout.addWidget(self._tabs, 1)
        self.setCentralWidget(body)
        vm.analysis_started.connect(self.analysis_started)
        vm.analysis_progress.connect(self._on_progress)
        vm.analysis_finished.connect(self._on_finished)
        vm.analysis_canceled.connect(self._on_canceled)
        vm.analysis_failed.connect(self._on_failed)
        self._render(vm.snapshot)
        if vm.analysis_running:
            self.analysis_started()

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers), self)
        table.setHorizontalHeaderLabels([get_text(header) for header in headers])
        table.setSortingEnabled(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return table

    def analysis_started(self) -> None:
        if self._progress is not None:
            return
        self._render(J1939AnalysisSnapshot((), ()))
        self._refresh.setEnabled(False)
        self._status.setText(get_text("j1939_monitor_analyzing"))
        self._progress = EtaProgressDialog(
            get_text("j1939_monitor_progress"), get_text("j1939_monitor_cancel"), self
        )
        self._progress.canceled.connect(self._vm.cancel)
        self._progress.start()

    def _on_progress(self, done: int, total: int) -> None:
        progress = self._progress
        if progress is None:
            return
        try:
            progress.report_progress(done, total)
        except RuntimeError:
            self._progress = None

    def _on_finished(self, snapshot: J1939AnalysisSnapshot) -> None:
        self._hide_progress()
        self._refresh.setEnabled(True)
        self._status.setText(get_text("j1939_monitor_complete").format(
            nodes=len(snapshot.nodes), sources=len(snapshot.diagnostics)
        ))
        self._render(snapshot)

    def _on_canceled(self) -> None:
        self._hide_progress()
        self._refresh.setEnabled(True)
        self._status.setText(get_text("j1939_monitor_canceled"))

    def _on_failed(self, message: str) -> None:
        self._hide_progress()
        self._refresh.setEnabled(True)
        self._status.setText(get_text("j1939_monitor_failed").format(message=message))

    def _hide_progress(self) -> None:
        progress = self._progress
        self._progress = None
        if progress is not None:
            progress.close()

    @staticmethod
    def _fill(table: QTableWidget, rows: list[list[str]]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column_index, value in enumerate(values):
                table.setItem(row_index, column_index, QTableWidgetItem(value))
        table.setSortingEnabled(True)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)

    def _render(self, snapshot: J1939AnalysisSnapshot) -> None:
        node_rows = [
            [
                f"0x{node.source_address:02X}",
                "" if node.identity_number is None else str(node.identity_number),
                "" if node.manufacturer_code is None else str(node.manufacturer_code),
                "" if node.function is None else str(node.function),
                self._vm.format_timestamp(node.timestamp),
                get_text("j1939_node_claimed_yes" if node.claimed else "j1939_node_claimed_no"),
            ]
            for node in snapshot.nodes
        ]
        self._fill(self._nodes, node_rows)
        diagnostic_rows: list[list[str]] = []
        for record in snapshot.diagnostics:
            dm1 = record.dm1
            lamp_values = (
                dm1.protect_lamp,
                dm1.amber_warning_lamp,
                dm1.red_stop_lamp,
                dm1.malfunction_indicator_lamp,
            )
            lamp_labels = (
                "j1939_lamp_protect",
                "j1939_lamp_amber",
                "j1939_lamp_red",
                "j1939_lamp_mil",
            )
            lamp_states = tuple(
                get_text(f"j1939_lamp_{state}")
                for state in ("off", "on", "error", "unavailable")
            )
            lamps = " · ".join(
                get_text(label).format(state=lamp_states[value])
                for label, value in zip(lamp_labels, lamp_values)
            )
            if not dm1.dtcs:
                diagnostic_rows.append([
                    f"0x{record.source_address:02X}",
                    get_text("j1939_dm1_pgn"),
                    get_text("j1939_empty_value"),
                    get_text("j1939_empty_value"),
                    get_text("j1939_empty_value"),
                    lamps,
                    self._vm.format_timestamp(record.timestamp),
                ])
            for dtc in dm1.dtcs:
                diagnostic_rows.append([
                    f"0x{record.source_address:02X}",
                    get_text("j1939_dm1_pgn"),
                    str(dtc.spn),
                    str(dtc.fmi),
                    str(dtc.occurrence_count),
                    lamps,
                    self._vm.format_timestamp(record.timestamp),
                ])
        self._fill(self._dtcs, diagnostic_rows)

    def refresh_timestamps(self) -> None:
        self._render(self._vm.snapshot)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._vm.analysis_running:
            self._vm.cancel()
        self._hide_progress()
        super().closeEvent(event)
