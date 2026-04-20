from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
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
from models.frame_selector import FrameSelector
from models.signal import Signal
from viewmodels.candidate_interpretations_viewmodel import (
    CandidateInterpretationsViewModel,
    CandidateItem,
    CandidateSeries,
)
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from viewmodels.view_signal import ViewSignal
from views.plot.time_axis import TimeAxisItem
from views.settings.mux_configuration_dialog import MuxConfigurationDialog
from views.settings.time_config_dialog import TimeConfigDialog
from views.widgets.time_filter_widget import TimeFilterWidget

if TYPE_CHECKING:
    from views.plot.plot_window_manager import PlotWindowManager


class CandidateInterpretationsWindow(QMainWindow):
    def __init__(
        self,
        vm: CandidateInterpretationsViewModel,
        *,
        time_config_vm: TimeConfigViewModel,
        plot_manager: PlotWindowManager | None = None,
        timezone_mode: str = "none",
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("candidate_interpretations_title"))
        self.resize(1550, 920)
        self._vm = vm
        self._time_vm = time_config_vm
        self._plot_manager = plot_manager
        self._timezone_mode = timezone_mode
        self._time_axis = TimeAxisItem(timezone_mode=self._timezone_mode, orientation="bottom")
        self._legend = None
        self._build_ui()
        self._setup_menu_bar()
        self._wire()
        self._set_timezone(self._timezone_mode)
        self._apply_parameters()
        self._vm.set_dataframe(getattr(self._vm, "_df", None))

    def _build_ui(self) -> None:
        self.can_ids = QListWidget(self)
        self.can_ids.setMinimumWidth(240)
        self.can_ids.setSelectionMode(QAbstractItemView.NoSelection)
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Search CAN ID...")
        self.time_filter = TimeFilterWidget(self._time_vm, parent=self)

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
        left_layout.addWidget(self.time_filter)
        left_layout.addLayout(left_top_buttons)
        left_layout.addWidget(self.search_box)
        left_layout.addWidget(self.can_ids, 1)
        left_layout.addLayout(mux_row)
        left_layout.addWidget(controls)
        left_layout.addWidget(QLabel(get_text("candidate_interpretations_candidates")))
        left_layout.addWidget(self.candidate_list, 2)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)

        self.plot = pg.PlotWidget(self, axisItems={"bottom": self._time_axis})
        self._legend = self.plot.addLegend(offset=(10, 10))
        self.plot.setLabel("left", "Decoded Value")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setMenuEnabled(False)
        self.plot.getViewBox().setMenuEnabled(False)
        self.plot.setContextMenuPolicy(Qt.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(self._open_plot_context_menu)

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
        self.search_box.textChanged.connect(self._apply_search_filter)
        self.time_filter.range_changed.connect(self._vm.set_time_range)

        self._vm.can_ids_changed.connect(self._set_can_ids)
        self._vm.candidate_list_changed.connect(self._set_candidate_list)
        self._vm.candidate_detail_changed.connect(self._set_details)
        self._vm.candidate_plot_changed.connect(self._set_plot_data)
        self._vm.recalculation_started.connect(self._on_recalculation_started)
        self._vm.recalculation_finished.connect(self._on_recalculation_finished)
        self._vm.recalculation_failed.connect(self._on_recalculation_failed)
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
        self._apply_search_filter()

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

    def _open_plot_context_menu(self, pos) -> None:
        candidate = self._vm.selected_candidate()
        if candidate is None or self._plot_manager is None:
            return

        menu = QMenu(self)
        add_last = menu.addAction(get_text("add_last_graph"))
        add_new = menu.addAction(get_text("add_new_graph"))
        action = menu.exec(self.plot.mapToGlobal(pos))

        if action == add_last:
            self._send_candidate_to_plot(candidate, use_last=True)
        elif action == add_new:
            self._send_candidate_to_plot(candidate, use_last=False)

    def _send_candidate_to_plot(self, candidate: CandidateItem, *, use_last: bool) -> None:
        signal = Signal(
            name=candidate.label,
            can_id=candidate.can_id,
            start_bit=candidate.start_bit,
            length=candidate.signal_length,
            le=candidate.byte_order == "LittleEndian",
            mux_start=candidate.mux_start,
            mux_bytes=candidate.mux_bytes,
            mux_value=candidate.mux_value,
            type_data=self._candidate_value_type(candidate),
        )
        view_signal = ViewSignal(
            signal=signal,
            selector=FrameSelector(selected_id=candidate.can_id, mode="exact"),
            color=QColor("#ff9f1c"),
            line_style="Solid",
            line_width=2,
        )
        self._plot_manager.add_view_signal(view_signal, use_last=use_last)

    @staticmethod
    def _candidate_value_type(candidate: CandidateItem) -> str:
        if candidate.value_type == "Signed":
            return "int"
        if candidate.value_type == "Float32":
            return "float32"
        return "uint"

    def _on_sensitivity_changed(self, value: int) -> None:
        self.sensitivity_value.setText(str(int(value)))

    def _run_recalculate(self, message: str) -> None:
        if self._vm.running:
            return
        self._apply_parameters()
        self._vm.set_checked_ids(self._checked_ids())
        self._show_recalc_dialog(message)
        self._set_controls_enabled(False)
        self._vm.recalculate()

    def _show_recalc_dialog(self, message: str) -> None:
        self._recalc_dialog = QProgressDialog(message, get_text("cancel"), 0, 0, self)
        self._recalc_dialog.setWindowTitle(get_text("candidate_interpretations_title"))
        self._recalc_dialog.setWindowModality(Qt.ApplicationModal)
        self._recalc_dialog.setMinimumDuration(0)
        self._recalc_dialog.canceled.connect(self._vm.cancel_recalculation)
        self._recalc_dialog.show()

    def _hide_recalc_dialog(self) -> None:
        if self._recalc_dialog is not None:
            self._recalc_dialog.close()
            self._recalc_dialog = None

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.btn_select_all,
            self.btn_select_none,
            self.btn_mux,
            self.btn_recalculate,
            self.min_length,
            self.max_length,
            self.granularity,
            self.endianness,
            self.value_type,
            self.sensitivity,
            self.can_ids,
        ):
            widget.setEnabled(enabled)

    def _on_recalculation_started(self) -> None:
        self._set_controls_enabled(False)

    def _on_recalculation_finished(self) -> None:
        self._hide_recalc_dialog()
        self._set_controls_enabled(True)

    def _on_recalculation_failed(self, message: str) -> None:
        QMessageBox.warning(
            self,
            get_text("candidate_interpretations_title"),
            get_text("failed_prefix").format(error=message),
        )

    def _apply_search_filter(self) -> None:
        needle = (self.search_box.text() or "").strip().upper()
        for row in range(self.can_ids.count()):
            item = self.can_ids.item(row)
            item.setHidden(bool(needle) and needle not in item.text().upper())


    def closeEvent(self, event) -> None:
        if self._vm.running:
            self._vm.cancel_recalculation()
        self._hide_recalc_dialog()
        super().closeEvent(event)
