from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from viewmodels.plot_viewmodel import PlotViewModel

_MAX_DISPLAY_POINTS = 30000
_SERIES_KIND_ROLE = Qt.ItemDataRole.UserRole + 1


class XYPlotWidget(QWidget):
    """Compare two signals already available in a Plot window."""

    def __init__(self, plot_vm: PlotViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot_vm = plot_vm
        self._timestamps = np.array([], dtype=float)
        self._x_values = np.array([], dtype=float)
        self._y_values = np.array([], dtype=float)
        self._build_ui()
        self._refresh_series_options()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.x_combo = QComboBox(self)
        self.y_combo = QComboBox(self)
        self.start_edit = QLineEdit(self)
        self.end_edit = QLineEdit(self)
        form.addRow(self._form_label("xy_x_signal_label"), self.x_combo)
        form.addRow(self._form_label("xy_y_signal_label"), self.y_combo)
        form.addRow(self._form_label("xy_start_label"), self.start_edit)
        form.addRow(self._form_label("xy_end_label"), self.end_edit)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.status_label = QLabel(self)
        self.snapshot_label = QLabel(get_text("xy_snapshot_label"), self)
        self.snapshot_label.setToolTip(get_text("xy_snapshot_tooltip"))
        self.refresh_button = QPushButton(get_text("xy_refresh_label"), self)
        self.apply_button = QPushButton(get_text("xy_apply_label"), self)
        self.export_button = QPushButton(get_text("xy_export_label"), self)
        actions.addWidget(self.status_label, 1)
        actions.addWidget(self.snapshot_label)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.apply_button)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        self.plot = pg.PlotWidget(self)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", get_text("xy_x_axis_label"))
        self.plot.setLabel("left", get_text("xy_y_axis_label"))
        layout.addWidget(self.plot, 1)
        self.apply_button.clicked.connect(self._refresh)
        self.refresh_button.clicked.connect(self.refresh_from_plot)
        self.export_button.clicked.connect(self._export)
        self.x_combo.currentIndexChanged.connect(self._reset_range_and_refresh)
        self.y_combo.currentIndexChanged.connect(self._reset_range_and_refresh)
        self.x_combo.currentTextChanged.connect(self._update_axis_labels)
        self.y_combo.currentTextChanged.connect(self._update_axis_labels)

    def _form_label(self, text_key: str) -> QLabel:
        label = QLabel(get_text(text_key), self)
        label.setMinimumWidth(145)
        return label

    def _refresh_series_options(self) -> None:
        previous_x = self.x_combo.currentData()
        previous_y = self.y_combo.currentData()
        self.x_combo.blockSignals(True)
        self.y_combo.blockSignals(True)
        self.x_combo.clear()
        self.y_combo.clear()
        for kind, name, label in self._plot_vm.series_choices():
            self.x_combo.addItem(label, name)
            self.x_combo.setItemData(self.x_combo.count() - 1, kind, _SERIES_KIND_ROLE)
            self.y_combo.addItem(label, name)
            self.y_combo.setItemData(self.y_combo.count() - 1, kind, _SERIES_KIND_ROLE)
        self._restore_combo(self.x_combo, previous_x, 0)
        self._restore_combo(self.y_combo, previous_y, min(1, self.y_combo.count() - 1))
        self.x_combo.blockSignals(False)
        self.y_combo.blockSignals(False)
        self._update_axis_labels()

    @staticmethod
    def _restore_combo(
        combo: QComboBox,
        previous: tuple[str, str] | None,
        fallback: int,
    ) -> None:
        for index in range(combo.count()):
            if XYPlotWidget._combo_choice(combo, index) == previous:
                combo.setCurrentIndex(index)
                return
        if combo.count():
            combo.setCurrentIndex(max(0, fallback))

    @staticmethod
    def _combo_choice(combo: QComboBox, index: int | None = None) -> tuple[str, str] | None:
        index = combo.currentIndex() if index is None else index
        name = combo.itemData(index)
        kind = combo.itemData(index, _SERIES_KIND_ROLE)
        if name is None or kind is None:
            return None
        return str(kind), str(name)

    def _reset_range_and_refresh(self) -> None:
        self.start_edit.clear()
        self.end_edit.clear()
        self._refresh()

    def refresh_from_plot(self) -> None:
        self._refresh_series_options()
        self.start_edit.clear()
        self.end_edit.clear()
        self._refresh()

    def _update_axis_labels(self, *_args: object) -> None:
        self.plot.setLabel("bottom", self.x_combo.currentText() or get_text("xy_x_axis_label"))
        self.plot.setLabel("left", self.y_combo.currentText() or get_text("xy_y_axis_label"))

    def _get_range(self) -> tuple[float | None, float | None]:
        start_text = self.start_edit.text().strip()
        end_text = self.end_edit.text().strip()
        start = float(start_text) if start_text else None
        end = float(end_text) if end_text else None
        if start is not None and end is not None and start > end:
            raise ValueError(get_text("xy_range_error"))
        return start, end

    def _aligned_data(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x_choice = self._combo_choice(self.x_combo)
        y_choice = self._combo_choice(self.y_combo)
        if x_choice is None or y_choice is None:
            return np.array([]), np.array([]), np.array([])
        if x_choice == y_choice:
            raise ValueError(get_text("xy_distinct_signals_error"))
        start, end = self._get_range()
        return self._plot_vm.align_xy(x_choice, y_choice, start=start, end=end)

    def _refresh(self, *_args: object) -> None:
        if self.x_combo.count() < 2:
            self.plot.clear()
            self.status_label.setText(get_text("xy_empty_message"))
            self._timestamps = self._x_values = self._y_values = np.array([], dtype=float)
            return
        try:
            timestamps, x_values, y_values = self._aligned_data()
        except (ValueError, KeyError) as exc:
            self.plot.clear()
            message = str(exc)
            if self.x_combo.count() < 2:
                message = get_text("xy_empty_message")
            self.status_label.setText(message)
            self._timestamps = self._x_values = self._y_values = np.array([], dtype=float)
            return
        self._timestamps, self._x_values, self._y_values = timestamps, x_values, y_values
        self.plot.clear()
        if timestamps.size:
            stride = max(1, int(np.ceil(timestamps.size / _MAX_DISPLAY_POINTS)))
            indices = np.arange(0, timestamps.size, stride)
            time_span = float(np.ptp(timestamps[indices]))
            colors = pg.colormap.get("viridis").map(
                (timestamps[indices] - float(timestamps[indices].min())) / time_span
                if time_span else np.zeros(indices.size),
                mode="qcolor",
            )
            self.plot.addItem(pg.ScatterPlotItem(
                x=x_values[indices], y=y_values[indices],
                pen=None, brush=colors, size=5,
            ))
        self.status_label.setText(get_text("xy_points_status").format(count=timestamps.size))

    def _export(self) -> None:
        if not self._timestamps.size:
            return
        x_choice = self._combo_choice(self.x_combo)
        y_choice = self._combo_choice(self.y_combo)
        path, _ = QFileDialog.getSaveFileName(
            self, get_text("xy_export_title"), "xy-data.csv", "CSV (*.csv)",
        )
        if not path:
            return
        try:
            assert x_choice is not None and y_choice is not None
            self._plot_vm.export_xy(
                path, self._timestamps, self._x_values, self._y_values,
                x_name=x_choice[1], y_name=y_choice[1],
            )
        except OSError as exc:
            QMessageBox.warning(self, get_text("xy_export_title"), str(exc))


class XYWindow(QMainWindow):
    """Standalone XY view retained for the Plot Tools command."""

    def __init__(self, plot_vm: PlotViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("xy_window_title"))
        self.resize(900, 650)
        self.xy_widget = XYPlotWidget(plot_vm, self)
        self.setCentralWidget(self.xy_widget)
