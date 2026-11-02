from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from config.app_config import get_text

if TYPE_CHECKING:
    from services.bus_statistics import BusStatisticsSnapshot
    from viewmodels.bus_statistics_viewmodel import BusStatisticsViewModel


class BusStatisticsWindow(QMainWindow):
    def __init__(self, vm: BusStatisticsViewModel, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("bus_statistics_title"))
        self.resize(850, 520)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._note = QLabel(get_text("bus_statistics_estimate_note"))
        self._note.setWordWrap(True)
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels([
            get_text("bus_statistics_id"), get_text("bus_statistics_frames"),
            get_text("bus_statistics_fps"), get_text("bus_statistics_period_min"),
            get_text("bus_statistics_period_mean"), get_text("bus_statistics_period_max"),
            get_text("bus_statistics_jitter"), get_text("bus_statistics_state"),
        ])
        self._table.setSortingEnabled(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(self._summary)
        layout.addWidget(self._note)
        layout.addWidget(self._table)
        self.setCentralWidget(body)
        vm.statistics_changed.connect(self._render)
        self._render(vm.snapshot)

    @staticmethod
    def _seconds(value: float | None) -> str:
        if value is None:
            return get_text("bus_statistics_unavailable")
        return get_text("bus_statistics_period_value").format(value=value * 1000)

    def _render(self, snapshot: BusStatisticsSnapshot) -> None:
        load = (
            get_text("bus_statistics_unavailable")
            if snapshot.estimated_load_percent is None
            else get_text("bus_statistics_load_percent").format(value=snapshot.estimated_load_percent)
        )
        bitrate = (
            get_text("bus_statistics_unavailable")
            if snapshot.bitrate is None
            else get_text("bus_statistics_bitrate").format(value=snapshot.bitrate)
        )
        self._summary.setText(get_text("bus_statistics_summary").format(
            fps=snapshot.frames_per_second, load=load, bitrate=bitrate,
            frames=snapshot.frame_count, ids=snapshot.can_id_count,
        ))
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(snapshot.can_ids))
        for row, item in enumerate(snapshot.can_ids):
            state = ", ".join(filter(None, [
                get_text("bus_statistics_new") if item.is_new else "",
                get_text("bus_statistics_missing") if item.is_missing else "",
                get_text("bus_statistics_unordered") if not item.periods_reliable else "",
            ])) or get_text("bus_statistics_active")
            values = [
                item.can_id, str(item.frame_count), f"{item.frames_per_second:.2f}",
                self._seconds(item.period_min), self._seconds(item.period_mean),
                self._seconds(item.period_max), self._seconds(item.jitter), state,
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(row, column, cell)
        self._table.setSortingEnabled(True)
        self._table.resizeColumnsToContents()
