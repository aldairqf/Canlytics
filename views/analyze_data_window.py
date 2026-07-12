from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QDialog,
)
import pyqtgraph as pg

from config.app_config import get_text
from views.icons import icon
from services.analyze_data import ByteSeries
from viewmodels.analyze_data_viewmodel import AnalyzeDataViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.plot.time_axis import TimeAxisItem
from views.settings.mux_configuration_dialog import MuxConfigurationDialog
from views.settings.time_config_dialog import TimeConfigDialog
from views.settings.time_filter_dialog import TimeFilterDialog
from views.widgets.list_filter import apply_text_filter

_CHIPS_PER_ROW = 4


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
        self._time_filter_state: dict[str, str] = {}
        self._build_ui()
        self._setup_menu_bar()
        self._setup_toolbar()
        self._wire()
        self._set_timezone(self._timezone_mode)
        self._apply_byte_selection()
        self._vm.set_dataframe(getattr(self._vm, "_df", None))

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Left panel ────────────────────────────────────────────────────────
        left_header = QLabel(get_text("can_id_panel_can_ids"))
        left_header.setObjectName("panel_header")

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Search CAN ID...")

        self.can_ids = QListWidget(self)
        self.can_ids.setMinimumWidth(200)

        left = QWidget(self)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 8)
        ll.setSpacing(6)
        ll.addWidget(left_header)
        ll.addWidget(self.search_box)
        ll.addWidget(self.can_ids)

        # ── Right panel ───────────────────────────────────────────────────────
        # MUX row
        self.btn_mux = QPushButton(get_text("mux_configuration_button"), self)
        self.mux_case = QComboBox(self)
        self.mux_case.setMinimumWidth(180)

        mux_row = QHBoxLayout()
        mux_row.addWidget(QLabel(get_text("mux_configuration_label")))
        mux_row.addWidget(self.btn_mux)
        mux_row.addWidget(QLabel(get_text("analyze_data_mux_case_label")))
        mux_row.addWidget(self.mux_case)
        mux_row.addStretch(1)

        # Byte selection
        byte_row = QHBoxLayout()
        byte_row.addWidget(QLabel(get_text("analyze_data_bytes_label")))
        self.btn_bytes_all = QPushButton(get_text("analyze_data_bytes_all"), self)
        self.btn_bytes_none = QPushButton(get_text("analyze_data_bytes_none"), self)
        self.btn_bytes_all.setFixedWidth(40)
        self.btn_bytes_none.setFixedWidth(48)
        byte_row.addWidget(self.btn_bytes_all)
        byte_row.addWidget(self.btn_bytes_none)
        for idx in range(8):
            cb = QCheckBox(f"B{idx}", self)
            cb.setChecked(True)
            self._byte_checks[idx] = cb
            byte_row.addWidget(cb)
        byte_row.addStretch(1)

        # Selected CAN ID headline
        self._selected_id_label = QLabel("—", self)
        self._selected_id_label.setObjectName("selected_id")

        # Statistics toggle button (starts collapsed)
        self._btn_stats = QPushButton("▸  Statistics", self)
        self._btn_stats.setCheckable(True)
        self._btn_stats.setChecked(False)
        self._btn_stats.setObjectName("stats_toggle")
        self._btn_stats.setFixedHeight(28)

        # Stats grid panel (hidden by default)
        self._stats_panel = QWidget(self)
        self._stats_panel.setVisible(False)
        self._stats_grid = QGridLayout(self._stats_panel)
        self._stats_grid.setContentsMargins(0, 4, 0, 8)
        self._stats_grid.setSpacing(6)

        # Plot
        self.plot = pg.PlotWidget(self, axisItems={"bottom": self._time_axis})
        self.plot.setLabel("left", "Value (Dec)")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self._legend = self.plot.addLegend(offset=(10, 10))

        # Assemble right panel
        right = QWidget(self)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 8, 8, 8)
        rl.setSpacing(6)
        rl.addLayout(mux_row)
        rl.addLayout(byte_row)
        rl.addWidget(self._selected_id_label)
        rl.addWidget(self._btn_stats)
        rl.addWidget(self._stats_panel)
        rl.addWidget(self.plot, 1)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    @staticmethod
    def _make_stat_chip(parent: QWidget, key: str, value: str) -> QFrame:
        chip = QFrame(parent)
        chip.setObjectName("stat_chip")
        inner = QVBoxLayout(chip)
        inner.setContentsMargins(10, 6, 10, 6)
        inner.setSpacing(1)
        key_lbl = QLabel(key, chip)
        key_lbl.setObjectName("stat_chip_key")
        key_lbl.setAlignment(Qt.AlignCenter)
        val_lbl = QLabel(value, chip)
        val_lbl.setObjectName("stat_chip_val")
        val_lbl.setAlignment(Qt.AlignCenter)
        inner.addWidget(key_lbl)
        inner.addWidget(val_lbl)
        return chip

    # ── Wiring ────────────────────────────────────────────────────────────────

    def _wire(self) -> None:
        self.can_ids.currentItemChanged.connect(self._on_can_id_changed)
        self.btn_mux.clicked.connect(self._open_mux_dialog)
        self.mux_case.currentTextChanged.connect(self._vm.set_selected_mux_case)
        self.search_box.textChanged.connect(self._apply_search_filter)
        self.btn_bytes_all.clicked.connect(self._select_all_bytes)
        self.btn_bytes_none.clicked.connect(self._select_no_bytes)
        for idx, checkbox in self._byte_checks.items():
            checkbox.toggled.connect(lambda _checked, _i=idx: self._apply_byte_selection())

        self._btn_stats.toggled.connect(self._toggle_details_panel)

        self._vm.can_ids_changed.connect(self._set_can_ids)
        self._vm.selected_id_changed.connect(self._select_can_id)
        self._vm.mux_cases_changed.connect(self._set_mux_cases)
        self._vm.summary_changed.connect(self._set_summary)
        self._vm.plot_changed.connect(self._set_plot_data)
        self._time_vm.timezone_changed.connect(self._set_timezone)
        self._time_vm.normalize_changed.connect(self._on_normalize_changed)

    def _setup_toolbar(self) -> None:
        tb = QToolBar(get_text("analyze_data_toolbar_title"), self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        self._action_time_config = QAction(icon("clock"), get_text("analyze_data_time_config_action"), self)
        self._action_time_config.setToolTip(get_text("analyze_data_time_config_tooltip"))
        self._action_time_config.triggered.connect(self._open_time_settings)
        tb.addAction(self._action_time_config)

        tb.addSeparator()

        self._action_time_filter = QAction(icon("sliders-horizontal"), get_text("analyze_data_time_filter_action"), self)
        self._action_time_filter.setToolTip(get_text("analyze_data_time_filter_tooltip"))
        self._action_time_filter.triggered.connect(self._open_time_filter)
        tb.addAction(self._action_time_filter)

        self._toolbar = tb

    def _setup_menu_bar(self) -> None:
        menu = self.menuBar().addMenu(get_text("menu_settings"))
        action = menu.addAction(get_text("menu_time_config"))
        action.triggered.connect(self._open_time_settings)
        time_filter_action = menu.addAction(get_text("menu_time_filter"))
        time_filter_action.triggered.connect(self._open_time_filter)
        menu.addSeparator()
        self._show_details_action = menu.addAction(get_text("candidate_show_details"))
        self._show_details_action.setCheckable(True)
        self._show_details_action.setChecked(False)
        self._show_details_action.toggled.connect(
            lambda v: (
                self._btn_stats.blockSignals(True),
                self._btn_stats.setChecked(v),
                self._btn_stats.blockSignals(False),
                self._toggle_details_panel(v),
            )
        )

    # ── Slot implementations ──────────────────────────────────────────────────

    def _open_time_settings(self) -> None:
        dlg = TimeConfigDialog(self._time_vm, parent=self)
        dlg.exec()

    def _open_time_filter(self) -> None:
        dlg = TimeFilterDialog(self._time_vm, state=self._time_filter_state, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._time_filter_state = dlg.get_state()
        ts_min, ts_max = dlg.get_range()
        self._vm.set_time_range(ts_min, ts_max)

    def _toggle_details_panel(self, visible: bool) -> None:
        self._stats_panel.setVisible(visible)
        self._btn_stats.setText("▾  Statistics" if visible else "▸  Statistics")
        self._show_details_action.blockSignals(True)
        self._show_details_action.setChecked(visible)
        self._show_details_action.blockSignals(False)

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
        can_id = current.text() if current else None
        self._vm.set_selected_id(can_id)
        self._selected_id_label.setText(can_id or "—")

    def _open_mux_dialog(self) -> None:
        dlg = MuxConfigurationDialog(self._vm.mux_configs, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._vm.set_mux_configuration(dlg.configs())

    def _apply_byte_selection(self) -> None:
        selected = {idx for idx, checkbox in self._byte_checks.items() if checkbox.isChecked()}
        self._vm.set_selected_bytes(selected)

    def _set_all_byte_checks(self, checked: bool) -> None:
        for checkbox in self._byte_checks.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        self._apply_byte_selection()

    def _select_all_bytes(self) -> None:
        self._set_all_byte_checks(True)

    def _select_no_bytes(self) -> None:
        self._set_all_byte_checks(False)

    def _set_can_ids(self, ids: list[str]) -> None:
        current_id = self._vm.selected_id
        self.can_ids.blockSignals(True)
        self.can_ids.clear()
        for can_id in ids:
            self.can_ids.addItem(can_id)
        if current_id and current_id in ids:
            matches = self.can_ids.findItems(current_id, Qt.MatchExactly)
            if matches:
                self.can_ids.setCurrentItem(matches[0])
        elif ids:
            self.can_ids.setCurrentRow(0)
        self.can_ids.blockSignals(False)
        self._apply_search_filter()

    def _select_can_id(self, can_id: str) -> None:
        if not can_id:
            self.can_ids.clearSelection()
            self._selected_id_label.setText("—")
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
        # Clear previous chips
        while self._stats_grid.count():
            item = self._stats_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Rebuild chips grid
        for i, (key, value) in enumerate(summary.items()):
            chip = self._make_stat_chip(self._stats_panel, str(key), str(value))
            self._stats_grid.addWidget(chip, i // _CHIPS_PER_ROW, i % _CHIPS_PER_ROW)

    def _set_plot_data(self, series: list[ByteSeries]) -> None:
        self.plot.clear()
        self._legend.clear()
        for item in series:
            self.plot.plot(item.x, item.y, pen=pg.mkPen(item.color, width=1.8), name=item.label)

    def _apply_search_filter(self) -> None:
        apply_text_filter(self.search_box, self.can_ids)
