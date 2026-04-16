from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QDialog,
)
import pyqtgraph as pg

from config.app_config import get_text
from viewmodels.analyze_data_viewmodel import AnalyzeDataViewModel, ByteSeries
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.plot.time_axis import TimeAxisItem
from views.settings.mux_configuration_dialog import MuxConfigurationDialog
from views.settings.time_config_dialog import TimeConfigDialog
from views.widgets.time_filter_widget import TimeFilterWidget


class AnalyzeDataWindow(QMainWindow):
    def __init__(
        self,
        vm: AnalyzeDataViewModel,
        *,
        time_config_vm: TimeConfigViewModel,
        timezone_mode: str = "none",
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("analyze_data_title"))
        self.resize(1400, 850)
        self._vm = vm
        self._time_vm = time_config_vm
        self._timezone_mode = timezone_mode
        self._time_axis = TimeAxisItem(timezone_mode=self._timezone_mode, orientation="bottom")
        self._byte_checks: dict[int, QCheckBox] = {}
        self._legend = None
        self._build_ui()
        self._setup_menu_bar()
        self._wire()
        self._set_timezone(self._timezone_mode)
        self._apply_byte_selection()
        self._vm.set_dataframe(getattr(self._vm, "_df", None))

    def _build_ui(self) -> None:
        self.can_ids = QListWidget(self)
        self.can_ids.setMinimumWidth(220)
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Search CAN ID...")
        self.time_filter = TimeFilterWidget(self._time_vm, parent=self)

        self.btn_mux = QPushButton(get_text("mux_configuration_button"), self)
        self.mux_case = QComboBox(self)
        self.mux_case.setMinimumWidth(180)

        self.summary = QPlainTextEdit(self)
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(140)

        byte_row = QHBoxLayout()
        byte_row.addWidget(QLabel(get_text("analyze_data_bytes_label")))
        for idx in range(8):
            cb = QCheckBox(f"B{idx}", self)
            cb.setChecked(True)
            self._byte_checks[idx] = cb
            byte_row.addWidget(cb)
        byte_row.addStretch(1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel(get_text("mux_configuration_label")))
        controls.addWidget(self.btn_mux)
        controls.addWidget(QLabel(get_text("analyze_data_mux_case_label")))
        controls.addWidget(self.mux_case)
        controls.addStretch(1)

        self.plot = pg.PlotWidget(self, axisItems={"bottom": self._time_axis})
        self._legend = self.plot.addLegend(offset=(10, 10))
        self.plot.setLabel("left", "Value (Dec)")
        self.plot.showGrid(x=True, y=True, alpha=0.25)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.addLayout(controls)
        right_layout.addLayout(byte_row)
        right_layout.addWidget(self.summary)
        right_layout.addWidget(self.plot, 1)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.time_filter)
        left_layout.addWidget(self.search_box)
        left_layout.addWidget(self.can_ids)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _wire(self) -> None:
        self.can_ids.currentItemChanged.connect(self._on_can_id_changed)
        self.btn_mux.clicked.connect(self._open_mux_dialog)
        self.mux_case.currentTextChanged.connect(self._vm.set_selected_mux_case)
        self.search_box.textChanged.connect(self._apply_search_filter)
        self.time_filter.range_changed.connect(self._vm.set_time_range)
        for idx, checkbox in self._byte_checks.items():
            checkbox.toggled.connect(lambda _checked, _i=idx: self._apply_byte_selection())

        self._vm.can_ids_changed.connect(self._set_can_ids)
        self._vm.selected_id_changed.connect(self._select_can_id)
        self._vm.mux_cases_changed.connect(self._set_mux_cases)
        self._vm.summary_changed.connect(self._set_summary)
        self._vm.plot_changed.connect(self._set_plot_data)
        self._time_vm.timezone_changed.connect(self._set_timezone)
        self._time_vm.normalize_changed.connect(self._on_normalize_changed)

    def _setup_menu_bar(self) -> None:
        menu = self.menuBar().addMenu(get_text("menu_settings"))
        action = menu.addAction(get_text("menu_time_config"))
        action.triggered.connect(self._open_time_settings)

    def _open_time_settings(self) -> None:
        dlg = TimeConfigDialog(self._time_vm, parent=self)
        dlg.exec()

    def _on_normalize_changed(self, normalize: bool) -> None:
        if normalize:
            self._set_timezone("none")

    def _set_timezone(self, tz: str) -> None:
        self._timezone_mode = (tz or "none").strip() or "none"
        self._time_axis.set_timezone(self._timezone_mode)
        if self._timezone_mode in ("none", None):
            self.plot.setLabel("bottom", "Time (s)")
        else:
            self.plot.setLabel("bottom", f"Time ({self._timezone_mode})")
        self.plot.repaint()

    def _on_can_id_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._vm.set_selected_id(current.text() if current else None)

    def _open_mux_dialog(self) -> None:
        dlg = MuxConfigurationDialog(self._vm.mux_configs, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._vm.set_mux_configuration(dlg.configs())

    def _apply_byte_selection(self) -> None:
        selected = {idx for idx, checkbox in self._byte_checks.items() if checkbox.isChecked()}
        self._vm.set_selected_bytes(selected)

    def _set_can_ids(self, ids: list[str]) -> None:
        self.can_ids.blockSignals(True)
        self.can_ids.clear()
        for can_id in ids:
            self.can_ids.addItem(can_id)
        self.can_ids.blockSignals(False)
        if ids and self.can_ids.currentRow() < 0:
            self.can_ids.setCurrentRow(0)
        self._apply_search_filter()

    def _select_can_id(self, can_id: str) -> None:
        if not can_id:
            self.can_ids.clearSelection()
            return
        matches = self.can_ids.findItems(can_id, Qt.MatchExactly)
        if matches:
            self.can_ids.setCurrentItem(matches[0])

    def _set_mux_cases(self, cases: list[str]) -> None:
        current = self.mux_case.currentText()
        self.mux_case.blockSignals(True)
        self.mux_case.clear()
        self.mux_case.addItems(cases or ["All"])
        if current and current in cases:
            self.mux_case.setCurrentText(current)
        self.mux_case.blockSignals(False)

    def _set_summary(self, summary: dict) -> None:
        lines = [f"{key}: {value}" for key, value in summary.items()]
        self.summary.setPlainText("\n".join(lines))

    def _set_plot_data(self, series: list[ByteSeries]) -> None:
        self.plot.clear()
        if self._legend is None:
            self._legend = self.plot.addLegend(offset=(10, 10))
        for item in series:
            self.plot.plot(item.x, item.y, pen=pg.mkPen(item.color, width=1.8), name=item.label)

    def _apply_search_filter(self) -> None:
        needle = (self.search_box.text() or "").strip().upper()
        for index in range(self.can_ids.count()):
            item = self.can_ids.item(index)
            item.setHidden(bool(needle) and needle not in item.text().upper())
