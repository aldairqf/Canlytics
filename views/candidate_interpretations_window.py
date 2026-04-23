from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
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
from services.session_state import SessionStateStore
from viewmodels.candidate_interpretations_viewmodel import (
    CandidateInterpretationsViewModel,
    CandidateItem,
    CandidateSeries,
)
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from viewmodels.view_signal import ViewSignal
from views.plot.time_axis import TimeAxisItem
from views.settings.candidate_filters_dialog import CandidateFiltersDialog
from views.settings.mux_configuration_dialog import MuxConfigurationDialog
from views.settings.time_config_dialog import TimeConfigDialog

if TYPE_CHECKING:
    from views.plot.plot_window_manager import PlotWindowManager


class CandidateInterpretationsWindow(QMainWindow):
    def __init__(
        self,
        vm: CandidateInterpretationsViewModel,
        *,
        time_config_vm: TimeConfigViewModel,
        session_state: SessionStateStore,
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
        self._session_state = session_state
        self._plot_manager = plot_manager
        self._timezone_mode = timezone_mode
        self._time_axis = TimeAxisItem(timezone_mode=self._timezone_mode, orientation="bottom")
        self._time_filter_state = {
            "ts_from": "",
            "ts_to": "",
            "date_from": "",
            "date_to": "",
        }
        self._amp_filter_enabled = False
        self._amp_filter_min = 0.0
        self._amp_filter_max = 255.0
        self._amp_suggested_min = 0.0
        self._amp_suggested_max = 255.0
        self._visual_ts_min: float | None = None
        self._visual_ts_max: float | None = None
        self._candidate_items: list[CandidateItem] = []
        self._legend = None
        self._build_ui()
        self._fit_initial_window_to_screen()
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

        params_grid = QGridLayout()
        params_grid.setHorizontalSpacing(12)
        params_grid.setVerticalSpacing(6)
        params_grid.addWidget(QLabel(get_text("candidate_interpretations_min_length"), self), 0, 0)
        params_grid.addWidget(self.min_length, 0, 1)
        params_grid.addWidget(QLabel(get_text("candidate_interpretations_max_length"), self), 0, 2)
        params_grid.addWidget(self.max_length, 0, 3)
        params_grid.addWidget(QLabel(get_text("candidate_interpretations_granularity"), self), 1, 0)
        params_grid.addWidget(self.granularity, 1, 1)
        params_grid.addWidget(QLabel(get_text("candidate_interpretations_endianness"), self), 1, 2)
        params_grid.addWidget(self.endianness, 1, 3)
        params_grid.addWidget(QLabel(get_text("candidate_interpretations_value_type"), self), 2, 0)
        params_grid.addWidget(self.value_type, 2, 1)
        params_grid.setColumnStretch(1, 1)
        params_grid.setColumnStretch(3, 1)

        sensitivity_row = QVBoxLayout()
        sensitivity_row.addWidget(self.sensitivity)
        sensitivity_labels = QHBoxLayout()
        sensitivity_labels.addWidget(QLabel(get_text("candidate_interpretations_sensitivity_low")))
        sensitivity_labels.addStretch(1)
        sensitivity_labels.addWidget(self.sensitivity_value)
        sensitivity_labels.addStretch(1)
        sensitivity_labels.addWidget(QLabel(get_text("candidate_interpretations_sensitivity_high")))
        sensitivity_row.addLayout(sensitivity_labels)

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
        controls_layout.addLayout(params_grid)
        controls_layout.addWidget(QLabel(get_text("candidate_interpretations_sensitivity"), self))
        controls_layout.addLayout(sensitivity_row)
        controls_layout.addWidget(self.btn_recalculate)
        controls_layout.addStretch(1)

        self.candidate_list = QListWidget(self)
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel(get_text("candidate_interpretations_can_ids")))
        left_layout.addLayout(left_top_buttons)
        left_layout.addWidget(self.search_box)
        left_layout.addWidget(self.can_ids, 1)
        left_layout.addLayout(mux_row)
        left_layout.addWidget(controls)
        candidates_header = QHBoxLayout()
        candidates_header.addWidget(QLabel(get_text("candidate_interpretations_candidates")))
        candidates_header.addStretch(1)
        self._tag_filter_combo = QComboBox(self)
        self._tag_filter_combo.addItems([
            get_text("candidate_filter_all"),
            get_text("candidate_hide_tagged"),
            get_text("candidate_show_only_tagged"),
        ])
        candidates_header.addWidget(self._tag_filter_combo)
        left_layout.addLayout(candidates_header)

        left_layout.addWidget(self.candidate_list, 2)

        self._tag_input = QLineEdit(self)
        self._tag_input.setPlaceholderText(get_text("candidate_tag_placeholder"))
        self._btn_tag = QPushButton(get_text("candidate_tag_button"), self)
        self._btn_untag = QPushButton(get_text("candidate_untag_button"), self)
        tag_row = QHBoxLayout()
        tag_row.addWidget(self._tag_input, 1)
        tag_row.addWidget(self._btn_tag)
        tag_row.addWidget(self._btn_untag)
        left_layout.addLayout(tag_row)

        self._btn_export_tags = QPushButton(get_text("candidate_export_tags"), self)
        self._btn_import_tags = QPushButton(get_text("candidate_import_tags"), self)
        tag_io_row = QHBoxLayout()
        tag_io_row.addStretch(1)
        tag_io_row.addWidget(self._btn_export_tags)
        tag_io_row.addWidget(self._btn_import_tags)
        left_layout.addLayout(tag_io_row)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self._details_label = QLabel(get_text("candidate_interpretations_details"))
        self.details.setVisible(False)
        self._details_label.setVisible(False)

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
        right_layout.addWidget(self._details_label)
        right_layout.addWidget(self.details)
        right_layout.addWidget(self.plot, 1)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _fit_initial_window_to_screen(self) -> None:
        screen = self.windowHandle().screen() if self.windowHandle() else None
        if screen is None:
            screen = QGuiApplication.screenAt(QApplication.primaryScreen().availableGeometry().center()) if QApplication.primaryScreen() else None
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        width = min(self.width(), max(900, available.width() - 40))
        height = min(self.height(), max(700, available.height() - 40))
        self.resize(width, height)

        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _wire(self) -> None:
        self.btn_select_all.clicked.connect(self._select_all_ids)
        self.btn_select_none.clicked.connect(self._select_none_ids)
        self.btn_mux.clicked.connect(self._open_mux_dialog)
        self.btn_recalculate.clicked.connect(self._recalculate)
        self.candidate_list.currentRowChanged.connect(self._vm.set_selected_candidate_index)
        self.candidate_list.currentRowChanged.connect(self._on_candidate_selection_changed)
        self._btn_tag.clicked.connect(self._on_candidate_tag)
        self._btn_untag.clicked.connect(self._on_candidate_untag)
        self._tag_filter_combo.currentIndexChanged.connect(lambda _: self._refresh_candidate_list_display())
        self._btn_export_tags.clicked.connect(self._export_tags)
        self._btn_import_tags.clicked.connect(self._import_tags)
        self.sensitivity.valueChanged.connect(self._on_sensitivity_changed)
        self.search_box.textChanged.connect(self._apply_search_filter)

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
        time_action = menu.addAction(get_text("menu_time_config"))
        time_action.triggered.connect(self._open_time_settings)
        filters_action = menu.addAction(get_text("menu_candidate_filters"))
        filters_action.triggered.connect(self._open_filters_settings)
        menu.addSeparator()
        self._show_details_action = menu.addAction(get_text("candidate_show_details"))
        self._show_details_action.setCheckable(True)
        self._show_details_action.setChecked(False)
        self._show_details_action.toggled.connect(self._toggle_details_panel)

    def _toggle_details_panel(self, visible: bool) -> None:
        self.details.setVisible(visible)
        self._details_label.setVisible(visible)

    def _open_time_settings(self) -> None:
        dlg = TimeConfigDialog(self._time_vm, parent=self)
        dlg.exec()

    def _open_filters_settings(self) -> None:
        dlg = CandidateFiltersDialog(
            time_config_vm=self._time_vm,
            time_filter_state=self._time_filter_state,
            amp_enabled=self._amp_filter_enabled,
            amp_min=self._amp_filter_min,
            amp_max=self._amp_filter_max,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        state = dlg.get_filter_state()
        self._time_filter_state = state["time_filter_state"]
        self._amp_filter_enabled = bool(state["amp_enabled"])
        self._amp_filter_min = float(state["amp_min"])
        self._amp_filter_max = float(state["amp_max"])
        self._visual_ts_min, self._visual_ts_max = dlg.time_filter.get_range()
        self._refresh_candidate_list_display()

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
        self._candidate_items = list(items)
        current_row = self.candidate_list.currentRow()
        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        for item in items:
            list_item = QListWidgetItem(item.label)
            list_item.setData(Qt.UserRole, item.label)
            list_item.setData(Qt.UserRole + 1, float(item.min_value) if item.min_value is not None else None)
            list_item.setData(Qt.UserRole + 2, float(item.max_value) if item.max_value is not None else None)
            self.candidate_list.addItem(list_item)
        self.candidate_list.blockSignals(False)
        self._update_amp_range(items)
        self._refresh_candidate_list_display()
        if not items:
            return
        row = current_row if 0 <= current_row < len(items) else 0
        self.candidate_list.setCurrentRow(row)
        self._vm.set_selected_candidate_index(row)

    def _set_details(self, details: dict) -> None:
        self._refresh_selected_candidate_view()

    def _set_plot_data(self, series: list[CandidateSeries]) -> None:
        self._refresh_selected_candidate_view()

    def _render_candidate_plot(self, candidate: CandidateItem | None) -> None:
        self.plot.clear()
        if candidate is None:
            return
        if self._legend is None:
            self._legend = self.plot.addLegend(offset=(10, 10))
        x, y = self._filtered_candidate_points(candidate)
        self.plot.plot(x, y, pen=pg.mkPen("#ff9f1c", width=1.8), name=candidate.label)
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


    def _update_amp_range(self, items: list[CandidateItem]) -> None:
        _EXTREME = 1e15
        if not items:
            gmin, gmax = 0.0, 100.0
        else:
            mins = [it.min_value for it in items
                    if it.min_value is not None and abs(it.min_value) < _EXTREME]
            maxs = [it.max_value for it in items
                    if it.max_value is not None and abs(it.max_value) < _EXTREME]
            if not mins and not maxs:
                mins = [max(it.min_value, -1e10) for it in items if it.min_value is not None]
                maxs = [min(it.max_value, 1e10) for it in items if it.max_value is not None]
            gmin = float(min(mins)) if mins else 0.0
            gmax = float(max(maxs)) if maxs else 100.0
            if gmax <= gmin:
                gmax = gmin + 1.0
        self._amp_suggested_min = gmin
        self._amp_suggested_max = gmax
        if not self._amp_filter_enabled:
            self._amp_filter_min = gmin
            self._amp_filter_max = gmax

    def _refresh_candidate_list_display(self) -> None:
        tags = self._session_state.get_signal_tags()
        tag_filter = self._tag_filter_combo.currentIndex()  
        amp_enabled = self._amp_filter_enabled
        fmin = self._amp_filter_min if amp_enabled else None
        fmax = self._amp_filter_max if amp_enabled else None
        for row in range(self.candidate_list.count()):
            list_item = self.candidate_list.item(row)
            if list_item is None:
                continue
            label = list_item.data(Qt.UserRole) or list_item.text()
            is_tagged = label in tags
            if is_tagged:
                list_item.setText(f"★ {tags[label]}  ({label})")
                list_item.setForeground(QColor("#ff9f1c"))
            else:
                list_item.setText(label)
                list_item.setData(Qt.ForegroundRole, None)
            tag_hidden = (tag_filter == 1 and is_tagged) or (tag_filter == 2 and not is_tagged)
            amp_hidden = False
            if amp_enabled:
                item_min = list_item.data(Qt.UserRole + 1)
                item_max = list_item.data(Qt.UserRole + 2)
                if item_min is not None and item_max is not None:
                    amp_hidden = item_min < fmin or item_max > fmax
            time_hidden = not self._candidate_passes_time_filter(row)
            list_item.setHidden(tag_hidden or amp_hidden or time_hidden)
        self._ensure_visible_candidate_selection()

    def _on_candidate_selection_changed(self, row: int) -> None:
        list_item = self.candidate_list.item(row)
        if list_item is None:
            self._tag_input.clear()
            self._refresh_selected_candidate_view()
            return
        label = list_item.data(Qt.UserRole) or list_item.text()
        tags = self._session_state.get_signal_tags()
        self._tag_input.setText(tags.get(label, ""))
        self._refresh_selected_candidate_view()

    def _candidate_passes_time_filter(self, row: int) -> bool:
        if row < 0 or row >= len(self._candidate_items):
            return False
        if self._visual_ts_min is None and self._visual_ts_max is None:
            return True
        item = self._candidate_items[row]
        for ts in item.timestamps:
            if self._visual_ts_min is not None and ts < self._visual_ts_min:
                continue
            if self._visual_ts_max is not None and ts > self._visual_ts_max:
                continue
            return True
        return False

    def _filtered_candidate_points(self, candidate: CandidateItem) -> tuple[list[float], list[float]]:
        x: list[float] = []
        y: list[float] = []
        for ts, value in zip(candidate.timestamps, candidate.values):
            if self._visual_ts_min is not None and ts < self._visual_ts_min:
                continue
            if self._visual_ts_max is not None and ts > self._visual_ts_max:
                continue
            x.append(float(ts))
            y.append(float(value))
        return x, y

    def _refresh_selected_candidate_view(self) -> None:
        candidate = self._vm.selected_candidate()
        current_row = self.candidate_list.currentRow()
        current_item = self.candidate_list.item(current_row) if current_row >= 0 else None
        if candidate is None or current_item is None or current_item.isHidden():
            self.details.clear()
            self._render_candidate_plot(None)
            return

        x, y = self._filtered_candidate_points(candidate)
        details = {
            "Label": candidate.label,
            "CAN ID": candidate.can_id,
            "Frame LEN": candidate.frame_len,
            "MUX": candidate.mux_label,
            "Signal Length": candidate.signal_length,
            "Frames": candidate.frames,
            "Frames in Filter": len(x),
            "Changes": candidate.changes,
            "Distinct Values": candidate.distinct_values,
            "Score": f"{candidate.score:.3f}",
            "Min": "" if candidate.min_value is None else self._format_number(candidate.min_value),
            "Max": "" if candidate.max_value is None else self._format_number(candidate.max_value),
            "Sample Values": ", ".join(candidate.sample_values),
        }
        self.details.setPlainText("\n".join(f"{key}: {value}" for key, value in details.items()))
        self._render_candidate_plot(candidate)

    def _ensure_visible_candidate_selection(self) -> None:
        current_row = self.candidate_list.currentRow()
        current_item = self.candidate_list.item(current_row) if current_row >= 0 else None
        if current_item is not None and not current_item.isHidden():
            self._refresh_selected_candidate_view()
            return

        for row in range(self.candidate_list.count()):
            item = self.candidate_list.item(row)
            if item is not None and not item.isHidden():
                self.candidate_list.setCurrentRow(row)
                return
        self.candidate_list.setCurrentRow(-1)
        self._refresh_selected_candidate_view()

    @staticmethod
    def _format_number(value: float) -> str:
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:.6f}".rstrip("0").rstrip(".")

    def _on_candidate_tag(self) -> None:
        row = self.candidate_list.currentRow()
        list_item = self.candidate_list.item(row)
        if list_item is None:
            return
        name = self._tag_input.text().strip()
        if not name:
            return
        label = list_item.data(Qt.UserRole) or list_item.text()
        self._session_state.set_signal_tag(label, name)
        self._refresh_candidate_list_display()

    def _on_candidate_untag(self) -> None:
        row = self.candidate_list.currentRow()
        list_item = self.candidate_list.item(row)
        if list_item is None:
            return
        label = list_item.data(Qt.UserRole) or list_item.text()
        self._session_state.remove_signal_tag(label)
        self._tag_input.clear()
        self._refresh_candidate_list_display()

    def _export_tags(self) -> None:
        tags = self._session_state.get_signal_tags()
        if not tags:
            QMessageBox.information(self, get_text("candidate_export_tags_title"), get_text("candidate_no_tags"))
            return
        default_dir = str(Path.home() / "Desktop" / "signal_tags.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, get_text("candidate_export_tags_title"), default_dir,
            "Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        lines = ["# CANAnalyze Signal Tags", "# Format: signal_label = user_name", ""]
        for label, name in tags.items():
            lines.append(f"{label} = {name}")
        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            QMessageBox.information(
                self, get_text("candidate_export_tags_title"),
                get_text("candidate_tags_exported").format(count=len(tags)) + f"\n{path}",
            )
        except Exception as exc:
            QMessageBox.warning(self, get_text("candidate_export_tags_title"), str(exc))

    def _import_tags(self) -> None:
        default_dir = str(Path.home() / "Desktop")
        path, _ = QFileDialog.getOpenFileName(
            self, get_text("candidate_import_tags_title"), default_dir,
            "Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            imported = 0
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                label, _, name = line.partition("=")
                label, name = label.strip(), name.strip()
                if label and name:
                    self._session_state.set_signal_tag(label, name)
                    imported += 1
            self._refresh_candidate_list_display()
            self._on_candidate_selection_changed(self.candidate_list.currentRow())
            QMessageBox.information(
                self, get_text("candidate_import_tags_title"),
                get_text("candidate_tags_imported").format(count=imported),
            )
        except Exception as exc:
            QMessageBox.warning(self, get_text("candidate_import_tags_title"), str(exc))

    def closeEvent(self, event) -> None:
        if self._vm.running:
            self._vm.cancel_recalculation()
        self._hide_recalc_dialog()
        super().closeEvent(event)



