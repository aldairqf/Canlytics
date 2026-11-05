from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from models.analysis_context import AnalysisMarker
from viewmodels.event_markers_viewmodel import EventMarkersViewModel
from viewmodels.range_diff_viewmodel import RangeDiffViewModel
from views.range_diff_window_manager import RangeDiffWindowManager


class EventMarkersWindow(QDialog):
    def __init__(
        self,
        vm: EventMarkersViewModel,
        *,
        timestamp_getter: Callable[[], float | None],
        range_diff_vm: RangeDiffViewModel,
        range_diff_manager: RangeDiffWindowManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("event_markers_title"))
        self.resize(520, 360)
        self._vm = vm
        self._timestamp_getter = timestamp_getter
        self._range_diff_vm = range_diff_vm
        self._range_diff_manager = range_diff_manager

        layout = QVBoxLayout(self)
        self._list = QListWidget(self)
        layout.addWidget(self._list)
        controls = QHBoxLayout()
        self._name = QComboBox(self)
        self._name.setEditable(True)
        self._name.addItems(["Event"])
        controls.addWidget(self._name)
        for state in ("ON", "OFF"):
            button = QPushButton(state, self)
            button.clicked.connect(lambda _checked=False, value=state: self._add(value))
            controls.addWidget(button)
        layout.addLayout(controls)
        self._compare = QPushButton(get_text("event_markers_compare"), self)
        self._compare.clicked.connect(self._compare_events)
        layout.addWidget(self._compare)
        self._vm.markers_changed.connect(self._refresh)
        self._refresh(self._vm.markers)

    def _refresh(self, markers: tuple[AnalysisMarker, ...]) -> None:
        self._list.clear()
        for marker in markers:
            self._list.addItem(f"{marker.sequence}: {marker.name} {marker.state} — {marker.timestamp:.6f}")
        names = sorted({marker.name for marker in markers})
        current = self._name.currentText()
        self._name.clear()
        self._name.addItems(names or ["Event"])
        self._name.setCurrentText(current if current in names else (names[0] if names else "Event"))
        self._compare.setEnabled(bool(self._vm.markers))

    def _add(self, state: str) -> None:
        timestamp = self._timestamp_getter()
        if timestamp is None:
            QMessageBox.information(self, self.windowTitle(), get_text("event_markers_no_data"))
            return
        try:
            self._vm.add_marker(self._name.currentText(), state, timestamp)
        except ValueError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))

    def _compare_events(self) -> None:
        bounds = self._range_diff_vm.dataframe_bounds()
        if bounds is None:
            return
        start, end = bounds
        comparisons = self._vm.comparisons(start, end)
        if not comparisons:
            QMessageBox.information(self, self.windowTitle(), get_text("event_markers_no_pairs"))
            return
        comparison = comparisons[-1]
        self._range_diff_vm.set_range_a(*comparison.range_a)
        self._range_diff_vm.set_range_b(*comparison.range_b)
        self._range_diff_manager.open_window()
        self._range_diff_vm.run_latest()
