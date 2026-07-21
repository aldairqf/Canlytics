from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal as QtSignal
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
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QDialog,
)
import pyqtgraph as pg

from config.app_config import get_text
from config.theme import get_active_theme
from views.icons import icon
from services.analyze_data import ByteSeries, MatrixEntry
from viewmodels.analyze_data_viewmodel import AnalyzeDataViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.plot.time_axis import TimeAxisItem
from views.settings.mux_configuration_dialog import MuxConfigurationDialog
from views.settings.time_config_dialog import TimeConfigDialog
from views.settings.time_filter_dialog import TimeFilterDialog
from views.widgets.eta_progress_dialog import EtaProgressDialog
from views.widgets.list_filter import apply_text_filter
from views.widgets.sparkline_widget import SparklineWidget

_CHIPS_PER_ROW = 4
_MATRIX_COLUMNS = 4
_MATRIX_CELL_CHUNK = 200  # cell widgets built per event-loop tick -- each entry's
# series is already decimated to ~150 points (build_matrix_summary), so cost per
# cell is uniform; unlike Candidate Interpretations, no frame-count budget needed.


class _ClickableFrame(QFrame):
    clicked = QtSignal()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


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
        self._precompute_dialog: EtaProgressDialog | None = None
        self._matrix_dialog: EtaProgressDialog | None = None
        self._matrix_requested = False
        self._build_ui()
        self._setup_menu_bar()
        self._setup_toolbar()
        self._wire()
        self._set_timezone(self._timezone_mode)
        self._apply_byte_selection()
        self._vm.set_dataframe(getattr(self._vm, "_df", None))
        self._vm.emit_current_state()
        # Lazy by default: only the selected id's stats are computed; precompute is opt-in.

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Center: selected-ID headline, collapsible stats, plot ───────────────
        self._selected_id_label = QLabel("—", self)
        self._selected_id_label.setObjectName("selected_id")

        self._btn_stats = QPushButton("▸  Statistics", self)
        self._btn_stats.setCheckable(True)
        self._btn_stats.setChecked(False)
        self._btn_stats.setObjectName("stats_toggle")
        self._btn_stats.setFixedHeight(28)

        header_row = QHBoxLayout()
        header_row.addWidget(self._selected_id_label)
        header_row.addStretch(1)
        header_row.addWidget(self._btn_stats)

        self._stats_panel = QWidget(self)
        self._stats_panel.setVisible(False)
        self._stats_grid = QGridLayout(self._stats_panel)
        self._stats_grid.setContentsMargins(0, 4, 0, 8)
        self._stats_grid.setSpacing(6)

        self.plot = pg.PlotWidget(self, axisItems={"bottom": self._time_axis})
        self.plot.setLabel("left", "Value (Dec)")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self._legend = self.plot.addLegend(offset=(10, 10))

        center = QWidget(self)
        cl = QVBoxLayout(center)
        cl.setContentsMargins(8, 8, 4, 8)
        cl.setSpacing(6)
        cl.addLayout(header_row)
        cl.addWidget(self._stats_panel)
        cl.addWidget(self.plot, 1)

        # ── Right panel: CAN ID search + list ────────────────────────────────────
        right_header = QLabel(get_text("can_id_panel_can_ids"))
        right_header.setObjectName("panel_header")

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText(get_text("can_id_search_placeholder"))

        self.can_ids = QListWidget(self)
        self.can_ids.setMinimumWidth(200)

        right = QWidget(self)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 8, 8, 8)
        rl.setSpacing(6)
        rl.addWidget(right_header)
        rl.addWidget(self.search_box)
        rl.addWidget(self.can_ids)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(splitter, get_text("analyze_data_tab_signal"))
        self.tabs.addTab(self._build_matrix_tab(), get_text("analyze_data_tab_matrix"))
        self.setCentralWidget(self.tabs)

    def _build_matrix_tab(self) -> QWidget:
        tab = QWidget(self)
        tl = QVBoxLayout(tab)

        self.chk_matrix_hide_flat = QCheckBox(get_text("analyze_data_matrix_hide_flat"), self)
        self.chk_matrix_live = QCheckBox(get_text("analyze_data_matrix_live"), self)
        self.chk_matrix_live.setToolTip(get_text("analyze_data_matrix_live_tooltip"))
        self.btn_matrix_refresh = QPushButton(get_text("analyze_data_matrix_refresh"), self)
        toolbar_row = QHBoxLayout()
        toolbar_row.addWidget(self.chk_matrix_hide_flat)
        toolbar_row.addWidget(self.chk_matrix_live)
        toolbar_row.addStretch(1)
        toolbar_row.addWidget(self.btn_matrix_refresh)
        tl.addLayout(toolbar_row)

        self.matrix_scroll = QScrollArea(tab)
        self.matrix_scroll.setWidgetResizable(True)
        self.matrix_container = QWidget()
        self.matrix_grid = QGridLayout(self.matrix_container)
        self.matrix_grid.setSpacing(8)
        self.matrix_scroll.setWidget(self.matrix_container)
        tl.addWidget(self.matrix_scroll, 1)

        self.matrix_empty_state = QLabel(get_text("analyze_data_matrix_empty_state"), tab)
        self.matrix_empty_state.setAlignment(Qt.AlignCenter)
        self.matrix_empty_state.setWordWrap(True)
        tl.addWidget(self.matrix_empty_state)
        self.matrix_empty_state.setVisible(False)

        self.matrix_building_label = QLabel("", tab)
        self.matrix_building_label.setAlignment(Qt.AlignCenter)
        tl.addWidget(self.matrix_building_label)
        self.matrix_building_label.setVisible(False)

        self._matrix_build_generation = 0
        return tab

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

    # ── Matrix view (AN1) ────────────────────────────────────────────────────────

    def _on_tab_changed(self, index: int) -> None:
        if index != 1:
            return
        self._matrix_requested = True
        if self._vm.matrix_built:
            self._refresh_matrix()
        else:
            self._vm.build_matrix()

    def _refresh_matrix(self) -> None:
        # Chunked via QTimer.singleShot(0, ...) -- building one QWidget cell per
        # entry synchronously froze the window at real scale (same bug fixed in
        # Candidate Interpretations' Matrix tab). _matrix_build_generation drops a
        # stale in-flight chunk if "hide flat"/refresh/tab re-entry supersedes it.
        self._matrix_build_generation += 1
        generation = self._matrix_build_generation
        entries = self._vm.get_matrix_entries(hide_flat=self.chk_matrix_hide_flat.isChecked())
        self._clear_matrix_grid()
        has_entries = bool(entries)
        self.matrix_scroll.setVisible(has_entries)
        self.matrix_empty_state.setVisible(not has_entries)
        self.matrix_building_label.setVisible(has_entries)
        if not has_entries:
            return
        self._fill_matrix_cells_incrementally(entries, generation)

    def _fill_matrix_cells_incrementally(self, entries: list, generation: int, start: int = 0) -> None:
        if generation != self._matrix_build_generation:
            return
        end = min(start + _MATRIX_CELL_CHUNK, len(entries))
        for i in range(start, end):
            row, col = divmod(i, _MATRIX_COLUMNS)
            self.matrix_grid.addWidget(self._build_matrix_cell(entries[i]), row, col)
        if end < len(entries):
            self.matrix_building_label.setText(
                get_text("analyze_data_matrix_building").format(done=end, total=len(entries))
            )
            QTimer.singleShot(0, lambda: self._fill_matrix_cells_incrementally(entries, generation, end))
            return
        self.matrix_building_label.setVisible(False)
        self.matrix_building_label.setText("")

    def _clear_matrix_grid(self) -> None:
        while self.matrix_grid.count():
            item = self.matrix_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _build_matrix_cell(self, entry: MatrixEntry) -> QWidget:
        cell = _ClickableFrame(self.matrix_container)
        cell.setFrameShape(QFrame.StyledPanel)
        cell.setFixedSize(220, 160)
        # Same "this changed" token as Diff Analyzer (CONST_SHIFT) and Real-Time's
        # byte highlight: theme.accent for movement, theme.border for flat/no signal.
        theme = get_active_theme()
        indicator = theme.accent if entry.has_movement else theme.border
        cell.setStyleSheet(f"QFrame {{ border-top: 3px solid {indicator}; }}")
        cell.setToolTip(
            get_text("analyze_data_matrix_cell_moved_tooltip")
            if entry.has_movement
            else get_text("analyze_data_matrix_cell_flat_tooltip")
        )
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        label = QLabel(f"{entry.can_id}  B{entry.byte_index}", cell)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        # SparklineWidget, not pg.PlotWidget: a grid of 100+ cells needs the
        # lightweight small-multiple pattern (one custom-painted polyline), not one
        # full QGraphicsView-backed chart per cell -- see sparkline_widget.py.
        sparkline = SparklineWidget(cell)
        sparkline.set_series(entry.series.x, entry.series.y, entry.series.color)
        layout.addWidget(sparkline, 1)

        cell.clicked.connect(lambda cid=entry.can_id: self._on_matrix_cell_clicked(cid))
        return cell

    def _on_matrix_cell_clicked(self, can_id: str) -> None:
        self._vm.set_selected_id(can_id)
        self.tabs.setCurrentIndex(0)

    # ── Wiring ────────────────────────────────────────────────────────────────

    def _wire(self) -> None:
        self.can_ids.currentItemChanged.connect(self._on_can_id_changed)
        self.mux_case.currentTextChanged.connect(self._vm.set_selected_mux_case)
        self.search_box.textChanged.connect(self._apply_search_filter)

        self._btn_stats.toggled.connect(self._toggle_details_panel)

        self._vm.can_ids_changed.connect(self._set_can_ids)
        self._vm.selected_id_changed.connect(self._select_can_id)
        self._vm.mux_cases_changed.connect(self._set_mux_cases)
        self._vm.precompute_started.connect(self._on_precompute_started)
        self._vm.precompute_progress.connect(self._on_precompute_progress)
        self._vm.precompute_finished.connect(self._on_precompute_done)
        self._vm.precompute_canceled.connect(self._on_precompute_done)
        self._vm.precompute_failed.connect(self._on_precompute_failed)
        self._vm.matrix_started.connect(self._on_matrix_started)
        self._vm.matrix_progress.connect(self._on_matrix_progress)
        self._vm.matrix_finished.connect(self._on_matrix_done)
        self._vm.matrix_canceled.connect(self._on_matrix_done)
        self._vm.matrix_failed.connect(self._on_matrix_failed)
        self._vm.summary_changed.connect(self._set_summary)
        self._vm.plot_changed.connect(self._set_plot_data)
        self._time_vm.timezone_changed.connect(self._set_timezone)
        self._time_vm.normalize_changed.connect(self._on_normalize_changed)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.btn_matrix_refresh.clicked.connect(self._force_refresh_matrix)
        self.chk_matrix_hide_flat.toggled.connect(self._refresh_matrix)
        self.chk_matrix_live.toggled.connect(self._vm.set_matrix_live)

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

        tb.addSeparator()

        self._action_mux = QAction(icon("grid"), get_text("mux_configuration_button"), self)
        self._action_mux.setToolTip(get_text("mux_configuration_label"))
        self._action_mux.triggered.connect(self._open_mux_dialog)
        tb.addAction(self._action_mux)

        tb.addWidget(QLabel(f" {get_text('analyze_data_mux_case_label')} ", self))
        self.mux_case = QComboBox(self)
        self.mux_case.setMinimumWidth(140)
        tb.addWidget(self.mux_case)

        tb.addSeparator()

        # Explicit opt-in to warm the lazy per-id stats cache, and the release valve back down.
        self._action_precompute = QAction(icon("gauge"), get_text("analyze_data_precompute_action"), self)
        self._action_precompute.setToolTip(get_text("analyze_data_precompute_tooltip"))
        self._action_precompute.triggered.connect(self._vm.precompute_all)
        tb.addAction(self._action_precompute)

        self._action_free_memory = QAction(icon("trash-2"), get_text("analyze_data_free_memory_action"), self)
        self._action_free_memory.setToolTip(get_text("analyze_data_free_memory_tooltip"))
        self._action_free_memory.triggered.connect(self._vm.free_memory)
        tb.addAction(self._action_free_memory)

        tb.addSeparator()

        tb.addWidget(QLabel(f" {get_text('analyze_data_bytes_label')} ", self))
        self._btn_bytes_all = QPushButton(get_text("analyze_data_bytes_all"), self)
        self._btn_bytes_all.clicked.connect(self._select_all_bytes)
        tb.addWidget(self._btn_bytes_all)
        self._btn_bytes_none = QPushButton(get_text("analyze_data_bytes_none"), self)
        self._btn_bytes_none.clicked.connect(self._select_no_bytes)
        tb.addWidget(self._btn_bytes_none)

        # Initial state comes from the vm (survives window close/reopen), not hardcoded True.
        selected = self._vm.selected_bytes
        for idx in range(8):
            checkbox = QCheckBox(f"B{idx}", self)
            checkbox.setChecked(idx in selected)
            checkbox.toggled.connect(lambda _checked, _i=idx: self._apply_byte_selection())
            tb.addWidget(checkbox)
            self._byte_checks[idx] = checkbox

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

    def _on_precompute_started(self) -> None:
        self._precompute_dialog = EtaProgressDialog(get_text("analyze_data_precompute_loading"), get_text("cancel"), self)
        self._precompute_dialog.setWindowTitle(get_text("analyze_data_title"))
        self._precompute_dialog.canceled.connect(self._vm.cancel_precompute)
        self._precompute_dialog.start()

    def _on_precompute_progress(self, done: int, total: int) -> None:
        if self._precompute_dialog is not None:
            self._precompute_dialog.report_progress(done, total)

    def _on_precompute_done(self) -> None:
        if self._precompute_dialog is not None:
            self._precompute_dialog.close()
            self._precompute_dialog = None

    def _on_precompute_failed(self, message: str) -> None:
        self._on_precompute_done()

    def _force_refresh_matrix(self) -> None:
        self._vm.build_matrix(force=True)

    def _on_matrix_started(self) -> None:
        self._matrix_dialog = EtaProgressDialog(get_text("analyze_data_matrix_loading"), get_text("cancel"), self)
        self._matrix_dialog.setWindowTitle(get_text("analyze_data_title"))
        self._matrix_dialog.canceled.connect(self._vm.cancel_matrix)
        self._matrix_dialog.start()

    def _on_matrix_progress(self, done: int, total: int) -> None:
        if self._matrix_dialog is not None:
            self._matrix_dialog.report_progress(done, total)

    def _on_matrix_done(self) -> None:
        if self._matrix_dialog is not None:
            self._matrix_dialog.close()
            self._matrix_dialog = None
        if self._matrix_requested and self.tabs.currentIndex() == 1:
            self._refresh_matrix()

    def _on_matrix_failed(self, message: str) -> None:
        self._on_matrix_done()

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

    def closeEvent(self, event) -> None:
        # shutdown() cancels+waits both precompute and matrix threads -- unlike
        # Diff Analyzer's Live mode, this VM has no long-lived session that must
        # survive a plain window close, so the same call used at app-exit is safe
        # here too (fixes the same B-19-class gap: cancel-without-wait would leave
        # a background thread racing a reopened window's running-guard).
        self._vm.shutdown()
        super().closeEvent(event)
