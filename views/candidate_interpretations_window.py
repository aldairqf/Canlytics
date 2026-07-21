from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal as QtSignal
from PySide6.QtGui import QAction, QBrush, QColor, QGuiApplication, QIcon, QPainter, QPixmap
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
    QFrame,
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
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg

from config.app_config import get_text
from config.theme import get_active_theme
from models.frame_selector import FrameSelector
from models.signal import Signal
from services.session_state import SessionStateStore
from services.candidate_interpretations import (
    CandidateItem,
    CandidateMatrixEntry,
    CandidateSeries,
    SignalCategory,
    build_candidate_matrix_entries,
)
from utils.can_id import can_id_sort_key
from viewmodels.candidate_interpretations_viewmodel import CandidateInterpretationsViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from viewmodels.view_signal import ViewSignal
from views.icons import icon
from views.plot.add_to_plot_menu import make_view_signal
from views.plot.time_axis import TimeAxisItem
from views.candidate_constraint_search import ConstraintSearchWindow
from views.settings.candidate_filters_dialog import CandidateFiltersDialog
from views.settings.mux_configuration_dialog import MuxConfigurationDialog
from views.settings.time_config_dialog import TimeConfigDialog
from views.widgets.eta_progress_dialog import EtaProgressDialog
from views.widgets.list_filter import apply_text_filter
from views.widgets.sparkline_widget import SparklineWidget

if TYPE_CHECKING:
    from views.plot.plot_window_manager import PlotWindowManager

# Index in self._value_type_filter_combo -> CandidateItem.value_type ("" = no filter).
_VALUE_TYPE_FILTER_VALUES = ("", "Unsigned", "Signed", "Float32")
_MATRIX_COLUMNS = 4
_MATRIX_CELL_CHUNK = 100  # cell widgets built per event-loop tick while building Matrix
# Candidates vary wildly in sample count (a few hundred to 480K+ on a real busy CAN
# ID) -- chunking by item COUNT let one tick land on a run of huge candidates and
# still freeze for seconds. Chunk by total frames instead, plus a hard item cap so
# a run of many small candidates can't rack up per-item overhead unbounded either.
_MATRIX_ENTRY_FRAME_BUDGET = 100_000
_MATRIX_ENTRY_ITEM_CAP = 60

# Index in self._category_filter_combo -> SignalCategory ("" = no filter). Also the
# fixed order Matrix sections render in.
_CATEGORY_FILTER_VALUES = (
    "",
    SignalCategory.COUNTER,
    SignalCategory.BINARY,
    SignalCategory.ENUM,
    SignalCategory.ANALOG,
    SignalCategory.CONSTANT,
    SignalCategory.OTHER,
)
_CATEGORY_LABEL_KEYS = {
    SignalCategory.COUNTER: "candidate_category_counter",
    SignalCategory.BINARY: "candidate_category_binary",
    SignalCategory.ENUM: "candidate_category_enum",
    SignalCategory.ANALOG: "candidate_category_analog",
    SignalCategory.CONSTANT: "candidate_category_constant",
    SignalCategory.OTHER: "candidate_category_other",
}
_CATEGORY_FIXED_COLORS = {
    SignalCategory.COUNTER: "#e0a458",
    SignalCategory.BINARY: "#5fb88b",
    SignalCategory.ENUM: "#c789dd",
}


def _category_display_name(category: str) -> str:
    return get_text(_CATEGORY_LABEL_KEYS.get(category, "candidate_category_other"))


def _category_color(category: str) -> str:
    if category in _CATEGORY_FIXED_COLORS:
        return _CATEGORY_FIXED_COLORS[category]
    if category == SignalCategory.ANALOG:
        return get_active_theme().accent
    return get_active_theme().text_muted


def _category_icon(category: str) -> QIcon:
    pixmap = QPixmap(10, 10)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(_category_color(category)))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, 10, 10)
    painter.end()
    return QIcon(pixmap)


class _ClickableFrame(QFrame):
    clicked = QtSignal()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class _CandidateListWidget(QListWidget):
    """QListWidget that skips hidden rows when navigating with arrow keys."""

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key not in (Qt.Key_Down, Qt.Key_Up):
            super().keyPressEvent(event)
            return
        step = 1 if key == Qt.Key_Down else -1
        row = self.currentRow() + step
        count = self.count()
        while 0 <= row < count:
            item = self.item(row)
            if item is not None and not item.isHidden():
                self.setCurrentItem(item)
                QTimer.singleShot(0, lambda i=item: self.scrollToItem(i, QAbstractItemView.EnsureVisible))
                return
            row += step


_SEARCH_PREFS_KEY = "candidate_interpretations"

class CandidateInterpretationsWindow(QMainWindow):
    def __init__(
        self,
        vm: CandidateInterpretationsViewModel,
        *,
        time_config_vm: TimeConfigViewModel,
        session_state: SessionStateStore,
        plot_manager: PlotWindowManager | None = None,
        real_time_analysis_manager=None,
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
        self._real_time_analysis_manager = real_time_analysis_manager
        self._matrix_dirty = True
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
        self._frames_filter_enabled = False
        self._frames_filter_min = 0
        self._frames_filter_max = 10_000_000
        self._endianness_filter = "All"
        self._min_length_filter = 0
        self._visual_ts_min: float | None = None
        self._visual_ts_max: float | None = None
        self._candidate_items: list[CandidateItem] = []
        self._displayed_items: list[CandidateItem] = []  # CI5: may be fewer than _candidate_items when grouped
        self._legend = None
        self._build_ui()
        self._fit_initial_window_to_screen()
        self._setup_menu_bar()
        self.menuBar().setVisible(False)
        self._setup_toolbar()
        self._wire()
        self._set_timezone(self._timezone_mode)
        self._restore_search_parameters()
        self._apply_parameters()
        self._vm.set_dataframe(getattr(self._vm, "_df", None))

    def _build_ui(self) -> None:
        self.can_ids = QListWidget(self)
        self.can_ids.setMinimumWidth(240)
        self.can_ids.setSelectionMode(QAbstractItemView.SingleSelection)
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText(get_text("can_id_search_placeholder"))
        self.chk_only_with_signals = QCheckBox(get_text("candidate_can_id_only_with_signals"), self)
        self.chk_only_with_signals.setToolTip(get_text("candidate_can_id_only_with_signals_tooltip"))

        self.btn_select_all = QPushButton(get_text("select_all"), self)
        self.btn_select_none = QPushButton(get_text("select_none"), self)
        self.btn_mux = QPushButton(get_text("mux_configuration_button"), self)
        self._recalc_dialog: EtaProgressDialog | None = None

        self.min_length = QSpinBox(self)
        self.min_length.setRange(1, 64)
        self.min_length.setValue(8)
        self.min_length.setToolTip(get_text("candidate_interpretations_min_length_tooltip"))

        self.max_length = QSpinBox(self)
        self.max_length.setRange(1, 64)
        self.max_length.setValue(8)
        self.max_length.setToolTip(get_text("candidate_interpretations_max_length_tooltip"))

        self.granularity = QSpinBox(self)
        self.granularity.setRange(1, 64)
        self.granularity.setValue(8)
        self.granularity.setToolTip(get_text("candidate_interpretations_granularity_tooltip"))

        self.endianness = QComboBox(self)
        self.endianness.addItems(
            [
                get_text("candidate_interpretations_try_both"),
                get_text("candidate_interpretations_little_endian"),
                get_text("candidate_interpretations_big_endian"),
            ]
        )
        self.endianness.setToolTip(get_text("candidate_interpretations_endianness_tooltip"))

        self.value_type = QComboBox(self)
        self.value_type.addItems(
            [
                get_text("candidate_interpretations_try_all"),
                get_text("candidate_interpretations_unsigned"),
                get_text("candidate_interpretations_signed"),
                get_text("candidate_interpretations_float32"),
            ]
        )
        self.value_type.setToolTip(get_text("candidate_interpretations_value_type_tooltip"))

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
        self.include_constant_checkbox = QCheckBox(get_text("candidate_interpretations_include_constant"), self)
        self.include_constant_checkbox.setToolTip(get_text("candidate_interpretations_include_constant_tooltip"))
        self.include_constant_checkbox.setChecked(True)
        params_grid.addWidget(self.include_constant_checkbox, 2, 2, 1, 2)
        params_grid.setColumnStretch(1, 1)
        params_grid.setColumnStretch(3, 1)

        self.btn_recalculate = QPushButton(get_text("candidate_interpretations_recalculate"), self)
        self.btn_recalculate.setObjectName("primary")

        left_top_buttons = QHBoxLayout()
        left_top_buttons.addWidget(self.btn_select_all)
        left_top_buttons.addWidget(self.btn_select_none)

        mux_row = QHBoxLayout()
        mux_row.addWidget(QLabel(get_text("mux_configuration_label")))
        mux_row.addWidget(self.btn_mux)
        mux_row.addStretch(1)

        self._btn_config = QPushButton(f"▸  {get_text('candidate_interpretations_advanced_parameters')}", self)
        self._btn_config.setCheckable(True)
        self._btn_config.setChecked(False)
        self._btn_config.setObjectName("stats_toggle")
        self._btn_config.setFixedHeight(28)

        self.advanced_group = QWidget(self)
        self.advanced_group.setVisible(False)
        advanced_layout = QVBoxLayout(self.advanced_group)
        advanced_layout.addLayout(params_grid)

        # ── Left: CAN ID selection + search configuration ───────────────────────
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel(get_text("candidate_interpretations_can_ids")))
        left_layout.addLayout(left_top_buttons)
        left_layout.addWidget(self.search_box)
        left_layout.addWidget(self.chk_only_with_signals)
        self._can_ids_empty = QLabel(get_text("candidate_interpretations_empty_ids"), self)
        self._can_ids_empty.setAlignment(Qt.AlignCenter)
        self._can_ids_empty.setWordWrap(True)
        self._can_ids_stack = QStackedWidget(self)
        self._can_ids_stack.addWidget(self.can_ids)
        self._can_ids_stack.addWidget(self._can_ids_empty)
        left_layout.addWidget(self._can_ids_stack, 1)
        left_layout.addLayout(mux_row)
        left_layout.addWidget(self._btn_config)
        left_layout.addWidget(self.advanced_group)
        left_layout.addWidget(self.btn_recalculate)

        # ── Persistent sidebar: filters + candidate list, same for both tabs ─────
        # 2-column grid, no per-row label/field pairing needed since Sort was
        # dropped -- 4 fields fit exactly 2x2, plus one full-width checkbox row.
        candidates_filter_grid = QGridLayout()
        candidates_filter_grid.setHorizontalSpacing(8)
        candidates_filter_grid.setVerticalSpacing(4)
        candidates_filter_grid.setColumnStretch(1, 1)
        candidates_filter_grid.setColumnStretch(3, 1)

        candidates_filter_grid.addWidget(QLabel(get_text("candidate_filter_type_label"), self), 0, 0)
        self._value_type_filter_combo = QComboBox(self)
        self._value_type_filter_combo.addItems([
            get_text("candidate_filter_type_all"),
            get_text("candidate_interpretations_unsigned"),
            get_text("candidate_interpretations_signed"),
            get_text("candidate_interpretations_float32"),
        ])
        candidates_filter_grid.addWidget(self._value_type_filter_combo, 0, 1)

        candidates_filter_grid.addWidget(QLabel(get_text("candidate_filter_tag_label"), self), 0, 2)
        self._tag_filter_combo = QComboBox(self)
        self._tag_filter_combo.addItems([
            get_text("candidate_filter_all"),
            get_text("candidate_hide_tagged"),
            get_text("candidate_show_only_tagged"),
        ])
        candidates_filter_grid.addWidget(self._tag_filter_combo, 0, 3)

        candidates_filter_grid.addWidget(QLabel(get_text("candidate_filter_category_label"), self), 1, 0)
        self._category_filter_combo = QComboBox(self)
        self._category_filter_combo.setToolTip(get_text("candidate_filter_category_tooltip"))
        self._category_filter_combo.addItems([
            get_text("candidate_category_all"),
            get_text("candidate_category_counter"),
            get_text("candidate_category_binary"),
            get_text("candidate_category_enum"),
            get_text("candidate_category_analog"),
            get_text("candidate_category_constant"),
            get_text("candidate_category_other"),
        ])
        candidates_filter_grid.addWidget(self._category_filter_combo, 1, 1)

        candidates_filter_grid.addWidget(QLabel(get_text("candidate_score_filter_label"), self), 1, 2)
        self._score_filter_spin = QDoubleSpinBox(self)
        self._score_filter_spin.setRange(0.0, 1.0)
        self._score_filter_spin.setSingleStep(0.05)
        self._score_filter_spin.setDecimals(2)
        self._score_filter_spin.setToolTip(get_text("candidate_score_filter_tooltip"))
        candidates_filter_grid.addWidget(self._score_filter_spin, 1, 3)

        # True multi-byte and true single-byte signals stay visible either way --
        # nothing is hidden unless the user checks this.
        self.chk_hide_multi_byte_fragments = QCheckBox(get_text("candidate_hide_multi_byte_fragments"), self)
        self.chk_hide_multi_byte_fragments.setToolTip(get_text("candidate_hide_multi_byte_fragments_tooltip"))
        candidates_filter_grid.addWidget(self.chk_hide_multi_byte_fragments, 2, 0, 1, 4)

        candidates_title = QLabel(get_text("candidate_interpretations_candidates"), self)
        candidates_title.setObjectName("panel_header")
        self._score_filter_count_label = QLabel(self)
        candidates_header = QHBoxLayout()
        candidates_header.addWidget(candidates_title)
        candidates_header.addStretch(1)
        candidates_header.addWidget(self._score_filter_count_label)

        self.candidate_list = _CandidateListWidget(self)
        self._candidate_empty = QLabel(get_text("candidate_interpretations_empty_candidates"), self)
        self._candidate_empty.setAlignment(Qt.AlignCenter)
        self._candidate_empty.setWordWrap(True)
        self._candidate_stack = QStackedWidget(self)
        self._candidate_stack.addWidget(self.candidate_list)
        self._candidate_stack.addWidget(self._candidate_empty)
        self._candidate_stack.setCurrentWidget(self._candidate_empty)

        self._tag_input = QLineEdit(self)
        self._tag_input.setPlaceholderText(get_text("candidate_tag_placeholder"))
        self._btn_tag = QPushButton(get_text("candidate_tag_button"), self)
        self._btn_untag = QPushButton(get_text("candidate_untag_button"), self)
        tag_row = QHBoxLayout()
        tag_row.addWidget(self._tag_input, 1)
        tag_row.addWidget(self._btn_tag)
        tag_row.addWidget(self._btn_untag)

        results = QWidget(self)
        results.setMinimumWidth(300)
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addLayout(candidates_filter_grid)
        results_layout.addLayout(candidates_header)
        results_layout.addWidget(self._candidate_stack, 1)
        results_layout.addLayout(tag_row)

        self._btn_details = QPushButton(f"▸  {get_text('candidate_interpretations_details')}", self)
        self._btn_details.setCheckable(True)
        self._btn_details.setChecked(False)
        self._btn_details.setObjectName("stats_toggle")
        self._btn_details.setFixedHeight(28)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details.setVisible(False)

        self.plot = pg.PlotWidget(self, axisItems={"bottom": self._time_axis})
        self._legend = self.plot.addLegend(offset=(10, 10))
        self.plot.setLabel("left", "Decoded Value")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setMenuEnabled(False)
        self.plot.getViewBox().setMenuEnabled(False)
        self.plot.setContextMenuPolicy(Qt.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(self._open_plot_context_menu)

        # ── Center: collapsible details + plot, dominant ─────────────────────────
        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self._btn_details)
        center_layout.addWidget(self.details)
        center_layout.addWidget(self.plot, 1)

        results_splitter = QSplitter(Qt.Horizontal, self)
        results_splitter.addWidget(left)
        results_splitter.addWidget(center)
        results_splitter.setStretchFactor(0, 0)
        results_splitter.setStretchFactor(1, 1)
        results_splitter.setSizes([380, 900])

        # Matrix is a lazy tab (built on first switch, like Analyze Data's), sourced
        # from the sidebar's un-hidden items so every active filter already applies.
        self.tabs = QTabWidget(self)
        self.tabs.addTab(results_splitter, get_text("candidate_interpretations_tab_results"))
        self.tabs.addTab(self._build_matrix_tab(), get_text("candidate_interpretations_tab_matrix"))

        # Sidebar sits outside the tabs -- filters and the candidate list never
        # disappear when switching between Results and Matrix.
        outer_splitter = QSplitter(Qt.Horizontal, self)
        outer_splitter.addWidget(self.tabs)
        outer_splitter.addWidget(results)
        outer_splitter.setStretchFactor(0, 1)
        outer_splitter.setStretchFactor(1, 0)
        outer_splitter.setSizes([1180, 320])
        self.setCentralWidget(outer_splitter)

    def _build_matrix_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        self.matrix_scroll = QScrollArea(tab)
        self.matrix_scroll.setWidgetResizable(True)
        self.matrix_container = QWidget()
        self.matrix_sections_layout = QVBoxLayout(self.matrix_container)
        self.matrix_sections_layout.setSpacing(10)
        self.matrix_sections_layout.addStretch(1)
        self.matrix_scroll.setWidget(self.matrix_container)
        layout.addWidget(self.matrix_scroll, 1)

        self.matrix_empty_state = QLabel(get_text("candidate_matrix_empty_state"), tab)
        self.matrix_empty_state.setAlignment(Qt.AlignCenter)
        self.matrix_empty_state.setWordWrap(True)
        layout.addWidget(self.matrix_empty_state)
        self.matrix_empty_state.setVisible(False)

        self.matrix_building_label = QLabel("", tab)
        self.matrix_building_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.matrix_building_label)
        self.matrix_building_label.setVisible(False)

        self._matrix_section_collapsed: dict[str, bool] = {}
        self._matrix_build_generation = 0
        return tab

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
        self.candidate_list.currentRowChanged.connect(self._on_candidate_row_changed)
        self.candidate_list.currentRowChanged.connect(self._on_candidate_selection_changed)
        self.chk_hide_multi_byte_fragments.toggled.connect(lambda _: self._refresh_candidate_list_display())
        self._score_filter_spin.valueChanged.connect(self._on_score_filter_spin_changed)
        self._btn_tag.clicked.connect(self._on_candidate_tag)
        self._btn_untag.clicked.connect(self._on_candidate_untag)
        self._tag_filter_combo.currentIndexChanged.connect(lambda _: self._refresh_candidate_list_display())
        self._value_type_filter_combo.currentIndexChanged.connect(lambda _: self._refresh_candidate_list_display())
        self._category_filter_combo.currentIndexChanged.connect(lambda _: self._refresh_candidate_list_display())
        self.search_box.textChanged.connect(self._apply_search_filter)
        self.chk_only_with_signals.toggled.connect(self._apply_search_filter)
        self._btn_details.toggled.connect(self._toggle_details_panel)
        self._btn_config.toggled.connect(self._toggle_config_panel)
        self.can_ids.itemActivated.connect(self._on_can_id_row_activated)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._vm.can_ids_changed.connect(self._set_can_ids)
        self._vm.candidate_list_changed.connect(self._set_candidate_list)
        self._vm.candidate_detail_changed.connect(self._set_details)
        self._vm.candidate_plot_changed.connect(self._set_plot_data)
        self._vm.recalculation_started.connect(self._on_recalculation_started)
        self._vm.recalculation_progress.connect(self._on_recalculation_progress)
        self._vm.recalculation_finished.connect(self._on_recalculation_finished)
        self._vm.recalculation_failed.connect(self._on_recalculation_failed)
        self._time_vm.timezone_changed.connect(self._set_timezone)
        self._time_vm.normalize_changed.connect(self._on_normalize_changed)

    def _setup_menu_bar(self) -> None:
        settings_menu = self.menuBar().addMenu(get_text("menu_settings"))
        time_action = settings_menu.addAction(get_text("menu_time_config"))
        time_action.triggered.connect(self._open_time_settings)
        settings_menu.addSeparator()
        self._show_details_action = settings_menu.addAction(get_text("candidate_show_details"))
        self._show_details_action.setCheckable(True)
        self._show_details_action.setChecked(False)
        self._show_details_action.toggled.connect(self._toggle_details_panel)

        tools_menu = self.menuBar().addMenu(get_text("menu_candidate_tools"))
        filters_action = tools_menu.addAction(get_text("menu_candidate_filters"))
        filters_action.triggered.connect(self._open_filters_settings)
        constraint_action = tools_menu.addAction(get_text("menu_candidate_constraint_search"))
        constraint_action.triggered.connect(self._open_constraint_search)
        tools_menu.addSeparator()
        export_tags_action = tools_menu.addAction(get_text("candidate_export_tags"))
        export_tags_action.triggered.connect(self._export_tags)
        import_tags_action = tools_menu.addAction(get_text("candidate_import_tags"))
        import_tags_action.triggered.connect(self._import_tags)

    def _setup_toolbar(self) -> None:
        tb = QToolBar(get_text("candidate_interpretations_toolbar_title"), self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        self._action_time_config = QAction(icon("clock"), get_text("candidate_toolbar_time_config"), self)
        self._action_time_config.setToolTip(get_text("candidate_interpretations_time_config_tooltip"))
        self._action_time_config.triggered.connect(self._open_time_settings)
        tb.addAction(self._action_time_config)

        tb.addSeparator()

        self._action_filters = QAction(icon("funnel"), get_text("candidate_toolbar_filters"), self)
        self._action_filters.triggered.connect(self._open_filters_settings)
        tb.addAction(self._action_filters)

        self._action_constraint_search = QAction(icon("crosshair"), get_text("candidate_toolbar_constraint_search"), self)
        self._action_constraint_search.setToolTip(get_text("candidate_interpretations_constraint_search_tooltip"))
        self._action_constraint_search.triggered.connect(self._open_constraint_search)
        tb.addAction(self._action_constraint_search)

        tb.addSeparator()

        self._action_export_tags = QAction(icon("download"), get_text("candidate_export_tags"), self)
        self._action_export_tags.triggered.connect(self._export_tags)
        tb.addAction(self._action_export_tags)

        self._action_import_tags = QAction(icon("upload"), get_text("candidate_import_tags"), self)
        self._action_import_tags.triggered.connect(self._import_tags)
        tb.addAction(self._action_import_tags)

        self._toolbar = tb
        self._update_active_filters_indicator()

    def _has_active_time_filter(self) -> bool:
        return any(str(value).strip() for value in self._time_filter_state.values())

    def _update_active_filters_indicator(self) -> None:
        active = (
            int(self._amp_filter_enabled)
            + int(self._frames_filter_enabled)
            + int(self._has_active_time_filter())
            + int(self._endianness_filter != "All")
            + int(self._min_length_filter > 0)
        )
        base = get_text("candidate_toolbar_filters")
        if active:
            self._action_filters.setText(f"{base} ({active})")
            self._action_filters.setToolTip(get_text("candidate_interpretations_filters_active_tooltip").format(count=active))
        else:
            self._action_filters.setText(base)
            self._action_filters.setToolTip(get_text("candidate_interpretations_filters_tooltip"))

    def _toggle_details_panel(self, visible: bool) -> None:
        self.details.setVisible(visible)
        self._btn_details.setText(f"{'▾' if visible else '▸'}  {get_text('candidate_interpretations_details')}")
        for control in (self._show_details_action, self._btn_details):
            control.blockSignals(True)
            control.setChecked(visible)
            control.blockSignals(False)

    def _toggle_config_panel(self, visible: bool) -> None:
        self.advanced_group.setVisible(visible)
        self._btn_config.setText(
            f"{'▾' if visible else '▸'}  {get_text('candidate_interpretations_advanced_parameters')}"
        )

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
            frames_enabled=self._frames_filter_enabled,
            frames_min=self._frames_filter_min,
            frames_max=self._frames_filter_max,
            endianness_filter=self._endianness_filter,
            min_length_filter=self._min_length_filter,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        state = dlg.get_filter_state()
        self._time_filter_state = state["time_filter_state"]
        self._amp_filter_enabled = bool(state["amp_enabled"])
        self._amp_filter_min = float(state["amp_min"])
        self._amp_filter_max = float(state["amp_max"])
        self._frames_filter_enabled = bool(state["frames_enabled"])
        self._frames_filter_min = int(state["frames_min"])
        self._frames_filter_max = int(state["frames_max"])
        self._endianness_filter = state["endianness_filter"]
        self._min_length_filter = int(state["min_length_filter"])
        self._visual_ts_min, self._visual_ts_max = dlg.time_filter.get_range()
        self._update_active_filters_indicator()
        self._refresh_candidate_list_display()
        self._refresh_candidate_list_display()

    def _open_constraint_search(self) -> None:
        if not self._candidate_items:
            QMessageBox.information(
                self,
                get_text("candidate_no_signals_title"),
                get_text("candidate_no_signals_message"),
            )
            return
        win = ConstraintSearchWindow(
            self._candidate_items,
            timezone_mode=self._timezone_mode,
            parent=self,
        )
        win.show()

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

    def _restore_search_parameters(self) -> None:
        prefs = self._session_state.get_window_prefs(_SEARCH_PREFS_KEY)
        if not prefs:
            return
        if "min_length" in prefs:
            self.min_length.setValue(int(prefs["min_length"]))
        if "max_length" in prefs:
            self.max_length.setValue(int(prefs["max_length"]))
        if "granularity" in prefs:
            self.granularity.setValue(int(prefs["granularity"]))
        if "endianness" in prefs:
            index = self.endianness.findText(str(prefs["endianness"]))
            if index >= 0:
                self.endianness.setCurrentIndex(index)
        if "value_type" in prefs:
            index = self.value_type.findText(str(prefs["value_type"]))
            if index >= 0:
                self.value_type.setCurrentIndex(index)
        if "include_constant" in prefs:
            self.include_constant_checkbox.setChecked(bool(prefs["include_constant"]))

    def _apply_parameters(self) -> None:
        self._vm.set_parameters(
            min_length=self.min_length.value(),
            max_length=self.max_length.value(),
            granularity=self.granularity.value(),
            endianness=self.endianness.currentText(),
            value_type=self.value_type.currentText(),
            include_constant=self.include_constant_checkbox.isChecked(),
        )
        self._session_state.set_window_prefs(_SEARCH_PREFS_KEY, {
            "min_length": self.min_length.value(),
            "max_length": self.max_length.value(),
            "granularity": self.granularity.value(),
            "endianness": self.endianness.currentText(),
            "value_type": self.value_type.currentText(),
            "include_constant": self.include_constant_checkbox.isChecked(),
        })

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
        has_ids = bool(ids)
        self._can_ids_stack.setCurrentWidget(self.can_ids if has_ids else self._can_ids_empty)
        self._apply_search_filter()

    def _checked_ids(self) -> set[str]:
        checked: set[str] = set()
        for row in range(self.can_ids.count()):
            item = self.can_ids.item(row)
            if item and item.checkState() == Qt.Checked:
                checked.add(item.text().strip().upper())
        return checked

    def _on_can_id_row_activated(self, item: QListWidgetItem) -> None:
        # Enter/double-click toggles the row's checkbox -- a full-row single-click
        # handler would double-toggle, since Qt already toggles on a direct
        # checkbox-glyph click before itemClicked fires for that same click.
        if item is None:
            return
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

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

    def set_checked_can_ids(self, can_ids: set[str]) -> None:
        """P1 handoff entry point (e.g. Diff Analyzer's "Analyze this ID as a signal"):
        scope the search to exactly these CAN IDs and recalculate right away."""
        wanted = {str(c).strip().upper() for c in can_ids}
        self.can_ids.blockSignals(True)
        for row in range(self.can_ids.count()):
            item = self.can_ids.item(row)
            if item:
                item.setCheckState(Qt.Checked if item.text().strip().upper() in wanted else Qt.Unchecked)
        self.can_ids.blockSignals(False)
        self._run_recalculate(get_text("candidate_interpretations_recalculating"))

    def _sorted_candidates(self, items: list[CandidateItem]) -> list[CandidateItem]:
        # Display-time only -- the vm's own order/list is untouched.
        return sorted(items, key=lambda it: (can_id_sort_key(it.can_id), -it.score))

    # ── Matrix tab (all current results, not raw bytes) ──────────────────────

    def _visible_displayed_items(self) -> list[CandidateItem]:
        """Exactly what the results list shows right now -- _displayed_items already
        reflects CI5 grouping, .isHidden() reflects every other active filter."""
        visible = []
        for row, item in enumerate(self._displayed_items):
            widget_item = self.candidate_list.item(row)
            if widget_item is not None and not widget_item.isHidden():
                visible.append(item)
        return visible

    def _on_visible_candidates_changed(self) -> None:
        if self.tabs.currentIndex() == 1:
            self._refresh_matrix_tab()
        else:
            self._matrix_dirty = True

    def _on_tab_changed(self, index: int) -> None:
        if index == 1 and self._matrix_dirty:
            self._refresh_matrix_tab()

    def _refresh_matrix_tab(self) -> None:
        # Everything below runs in small chunks via QTimer.singleShot(0, ...) instead
        # of one giant loop -- with thousands of candidates, building every decimated
        # series + every cell widget synchronously froze the window (user-reported
        # "No responde"). _matrix_build_generation lets a stale in-flight chunk detect
        # it was superseded (tab re-entered, filters changed again) and stop quietly.
        self._matrix_build_generation += 1
        generation = self._matrix_build_generation
        self._clear_matrix_sections()
        items = self._visible_displayed_items()
        self._matrix_dirty = False

        has_items = bool(items)
        self.matrix_scroll.setVisible(has_items)
        self.matrix_empty_state.setVisible(not has_items)
        self.matrix_building_label.setVisible(has_items)
        if not has_items:
            return
        self._build_matrix_entries_incrementally(items, generation)

    def _build_matrix_entries_incrementally(
        self, items: list[CandidateItem], generation: int, start: int = 0, acc: list | None = None
    ) -> None:
        if generation != self._matrix_build_generation:
            return
        acc = [] if acc is None else acc
        end = start
        frames_budgeted = 0
        while (
            end < len(items)
            and end - start < _MATRIX_ENTRY_ITEM_CAP
            and (end == start or frames_budgeted < _MATRIX_ENTRY_FRAME_BUDGET)
        ):
            frames_budgeted += max(1, items[end].frames)
            end += 1
        acc.extend(build_candidate_matrix_entries(items[start:end]))
        if end < len(items):
            self.matrix_building_label.setText(get_text("candidate_matrix_building").format(done=end, total=len(items)))
            QTimer.singleShot(0, lambda: self._build_matrix_entries_incrementally(items, generation, end, acc))
            return
        # Separate tick -- the last entries chunk and the first cell chunk must not
        # run back-to-back in the same call stack (that glued spike measured ~500ms).
        QTimer.singleShot(0, lambda: self._start_matrix_cell_build(acc, generation))

    def _start_matrix_cell_build(self, entries: list[CandidateMatrixEntry], generation: int) -> None:
        if generation != self._matrix_build_generation:
            return
        by_category: dict[str, list[CandidateMatrixEntry]] = {}
        for entry in entries:
            by_category.setdefault(entry.signal_category, []).append(entry)

        queue: list[tuple[QGridLayout, int, int, CandidateMatrixEntry]] = []
        insert_at = self.matrix_sections_layout.count() - 1  # keep the trailing stretch last
        for category in _CATEGORY_FILTER_VALUES[1:]:
            group = by_category.get(category)
            if not group:
                continue
            section, body_grid = self._build_matrix_section_shell(category, group)
            self.matrix_sections_layout.insertWidget(insert_at, section)
            insert_at += 1
            for i, entry in enumerate(group):
                row, col = divmod(i, _MATRIX_COLUMNS)
                queue.append((body_grid, row, col, entry))

        QTimer.singleShot(0, lambda: self._fill_matrix_cells_incrementally(queue, generation, total=len(queue)))

    def _fill_matrix_cells_incrementally(self, queue, generation: int, *, total: int, start: int = 0) -> None:
        if generation != self._matrix_build_generation:
            return
        end = min(start + _MATRIX_CELL_CHUNK, len(queue))
        for grid, row, col, entry in queue[start:end]:
            grid.addWidget(self._build_matrix_cell(entry), row, col)
        if end < len(queue):
            self.matrix_building_label.setText(get_text("candidate_matrix_building").format(done=end, total=total))
            QTimer.singleShot(0, lambda: self._fill_matrix_cells_incrementally(queue, generation, total=total, start=end))
            return
        self.matrix_building_label.setVisible(False)
        self.matrix_building_label.setText("")

    def _clear_matrix_sections(self) -> None:
        while self.matrix_sections_layout.count() > 1:  # keep the trailing stretch
            item = self.matrix_sections_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _build_matrix_section_shell(self, category: str, entries: list[CandidateMatrixEntry]) -> tuple[QWidget, QGridLayout]:
        section = QWidget(self.matrix_container)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(6)

        expanded = not self._matrix_section_collapsed.get(category, False)
        header = QPushButton(section)
        header.setCheckable(True)
        header.setChecked(expanded)
        header.setObjectName("stats_toggle")
        header.setIcon(_category_icon(category))

        body = QWidget(section)
        body_grid = QGridLayout(body)
        body_grid.setSpacing(8)
        body.setVisible(expanded)

        def _set_header_text(checked: bool) -> None:
            header.setText(f"{'▾' if checked else '▸'}  {_category_display_name(category)} ({len(entries)})")

        _set_header_text(expanded)
        header.toggled.connect(_set_header_text)
        header.toggled.connect(body.setVisible)
        header.toggled.connect(lambda checked, cat=category: self._matrix_section_collapsed.__setitem__(cat, not checked))

        section_layout.addWidget(header)
        section_layout.addWidget(body)
        return section, body_grid

    def _build_matrix_cell(self, entry: CandidateMatrixEntry) -> QWidget:
        cell = _ClickableFrame(self.matrix_container)
        cell.setFrameShape(QFrame.StyledPanel)
        cell.setFixedSize(220, 160)
        cell.setToolTip(get_text("candidate_matrix_cell_tooltip"))
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        label = QLabel(entry.title, cell)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        sparkline = SparklineWidget(cell)
        sparkline.set_series(entry.series.x, entry.series.y, _category_color(entry.signal_category))
        layout.addWidget(sparkline, 1)

        cell.clicked.connect(lambda lbl=entry.label: self._on_matrix_cell_clicked(lbl))
        return cell

    def _on_matrix_cell_clicked(self, label: str) -> None:
        self.tabs.setCurrentIndex(0)
        self.focus_candidate(label)

    def _rebuild_candidate_list_widget(self) -> None:
        # CI5: grouping collapses every interpretation of the same bit range into
        # one representative row -- _displayed_items (not _candidate_items) is what
        # actually lines up with the widget's rows from here on.
        self._displayed_items = self._candidate_items

        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        for item in self._displayed_items:
            list_item = QListWidgetItem(_category_icon(item.signal_category), item.label)
            list_item.setData(Qt.UserRole, item.label)
            list_item.setData(Qt.UserRole + 1, float(item.min_value) if item.min_value is not None else None)
            list_item.setData(Qt.UserRole + 2, float(item.max_value) if item.max_value is not None else None)
            list_item.setData(Qt.UserRole + 3, int(item.frames))
            list_item.setData(Qt.UserRole + 4, item.value_type)
            list_item.setData(Qt.UserRole + 5, float(item.score))
            list_item.setData(Qt.UserRole + 6, item.byte_order)
            list_item.setData(Qt.UserRole + 7, int(item.signal_length))
            list_item.setData(Qt.UserRole + 9, bool(item.is_multi_byte_fragment))
            list_item.setData(Qt.UserRole + 10, item.signal_category)
            self.candidate_list.addItem(list_item)
        self.candidate_list.blockSignals(False)

    def _set_candidate_list(self, items: list[CandidateItem]) -> None:
        current_item = self.candidate_list.currentItem()
        current_label = current_item.data(Qt.UserRole) if current_item is not None else None

        self._candidate_items = self._sorted_candidates(list(items))
        self._rebuild_candidate_list_widget()
        self._update_amp_range(self._candidate_items)
        self._refresh_candidate_list_display()
        self._refresh_can_id_annotations()
        if not self._displayed_items:
            return
        if not self._select_candidate_by_label(current_label):
            self.candidate_list.setCurrentRow(0)
            self._vm.set_selected_candidate_label(self._displayed_items[0].label)

    def focus_candidate(self, label: str) -> bool:
        """Matrix window drill-in: select this candidate in the results list (must
        already pass the current type/tag/score filters to be visible)."""
        return self._select_candidate_by_label(label)

    def _select_candidate_by_label(self, label: str | None) -> bool:
        if not label:
            return False
        for row, item in enumerate(self._displayed_items):
            if item.label == label:
                self.candidate_list.setCurrentRow(row)
                self._vm.set_selected_candidate_label(label)
                return True
        return False

    def _on_candidate_row_changed(self, row: int) -> None:
        label = self._displayed_items[row].label if 0 <= row < len(self._displayed_items) else None
        self._vm.set_selected_candidate_label(label)

    def _on_score_filter_spin_changed(self, value: float) -> None:
        self._refresh_candidate_list_display()

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
        self.plot.plot(
            x,
            y,
            pen=pg.mkPen(get_active_theme().warn, width=1.8),
            name=self._candidate_display_name(candidate),
        )
        self.plot.enableAutoRange()
        self.plot.autoRange()

    def _open_plot_context_menu(self, pos) -> None:
        candidate = self._vm.selected_candidate()
        if candidate is None:
            return

        menu = QMenu(self)
        add_new = add_last = None
        if self._plot_manager is not None:
            add_new = menu.addAction(get_text("add_new_graph"))
            add_last = menu.addAction(get_text("add_last_graph"))
        confirm_action = None
        if self._real_time_analysis_manager is not None:
            if add_new is not None:
                menu.addSeparator()
            confirm_action = menu.addAction(get_text("candidate_confirm_in_realtime"))
        if menu.isEmpty():
            return

        action = menu.exec(self.plot.mapToGlobal(pos))
        if action is None:
            return
        if action is confirm_action:
            self._real_time_analysis_manager.open_window_for_can_id(
                candidate.can_id, source=get_text("candidate_interpretations_title")
            )
        elif action in (add_new, add_last):
            view_signal = self._build_view_signal_for_candidate(candidate)
            self._plot_manager.add_view_signal(view_signal, use_last=(action is add_last))

    def _build_view_signal_for_candidate(self, candidate: CandidateItem) -> ViewSignal:
        signal = Signal(
            name=self._candidate_display_name(candidate),
            can_id=candidate.can_id,
            start_bit=candidate.start_bit,
            length=candidate.signal_length,
            le=candidate.byte_order == "LittleEndian",
            mux_start=candidate.mux_start,
            mux_bytes=candidate.mux_bytes,
            mux_value=candidate.mux_value,
            type_data=self._candidate_value_type(candidate),
        )
        return make_view_signal(
            signal,
            FrameSelector(selected_id=candidate.can_id, mode="exact"),
            color=get_active_theme().warn,
        )

    def _candidate_display_name(self, candidate: CandidateItem) -> str:
        tag_name = self._session_state.get_signal_tags().get(candidate.label, "").strip()
        return tag_name or candidate.label

    @staticmethod
    def _candidate_value_type(candidate: CandidateItem) -> str:
        if candidate.value_type == "Signed":
            return "int"
        if candidate.value_type == "Float32":
            return "float32"
        return "uint"

    def _run_recalculate(self, message: str) -> None:
        if self._vm.running:
            return
        self._apply_parameters()
        self._vm.set_checked_ids(self._checked_ids())
        self._show_recalc_dialog(message)
        self._set_controls_enabled(False)
        self._vm.recalculate()

    def _show_recalc_dialog(self, message: str) -> None:
        self._recalc_dialog = EtaProgressDialog(message, get_text("cancel"), self)
        self._recalc_dialog.setWindowTitle(get_text("candidate_interpretations_title"))
        self._recalc_dialog.canceled.connect(self._vm.cancel_recalculation)
        self._recalc_dialog.start()

    def _on_recalculation_progress(self, done: int, total: int) -> None:
        if self._recalc_dialog is not None:
            self._recalc_dialog.report_progress(done, total)

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
            self.advanced_group,
            self.min_length,
            self.max_length,
            self.granularity,
            self.endianness,
            self.value_type,
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
        apply_text_filter(self.search_box, self.can_ids)
        if self.chk_only_with_signals.isChecked():
            counts = self._can_id_candidate_counts()
            for row in range(self.can_ids.count()):
                item = self.can_ids.item(row)
                if item is not None and not item.isHidden():
                    if counts.get(item.text().strip().upper(), 0) == 0:
                        item.setHidden(True)

    def _can_id_candidate_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for candidate in self._candidate_items:
            counts[candidate.can_id] = counts.get(candidate.can_id, 0) + 1
        return counts

    def _refresh_can_id_annotations(self) -> None:
        """Dim CAN IDs with zero candidates (still selectable, just de-emphasized) and
        tooltip the count for the rest; chk_only_with_signals can hide the zero ones."""
        counts = self._can_id_candidate_counts()
        muted = QColor(get_active_theme().text_muted)
        for row in range(self.can_ids.count()):
            item = self.can_ids.item(row)
            if item is None:
                continue
            count = counts.get(item.text().strip().upper(), 0)
            if count > 0:
                item.setData(Qt.ForegroundRole, None)
                item.setToolTip(get_text("candidate_can_id_tooltip_found").format(count=count))
            else:
                item.setForeground(muted)
                item.setToolTip(get_text("candidate_can_id_tooltip_none"))
        self._apply_search_filter()


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
        type_filter_idx = self._value_type_filter_combo.currentIndex()
        type_filter_value = (
            _VALUE_TYPE_FILTER_VALUES[type_filter_idx]
            if 0 <= type_filter_idx < len(_VALUE_TYPE_FILTER_VALUES)
            else ""
        )
        amp_enabled = self._amp_filter_enabled
        fmin = self._amp_filter_min if amp_enabled else None
        fmax = self._amp_filter_max if amp_enabled else None
        frames_enabled = self._frames_filter_enabled
        min_score = self._score_filter_spin.value()
        hide_fragments = self.chk_hide_multi_byte_fragments.isChecked()
        category_filter_idx = self._category_filter_combo.currentIndex()
        category_filter_value = (
            _CATEGORY_FILTER_VALUES[category_filter_idx]
            if 0 <= category_filter_idx < len(_CATEGORY_FILTER_VALUES)
            else ""
        )
        for row in range(self.candidate_list.count()):
            list_item = self.candidate_list.item(row)
            if list_item is None:
                continue
            label = list_item.data(Qt.UserRole) or list_item.text()
            is_tagged = label in tags
            if is_tagged:
                list_item.setText(f"★ {tags[label]}  ({label})")
                list_item.setForeground(QColor(get_active_theme().warn))
            else:
                list_item.setText(label)
                list_item.setData(Qt.ForegroundRole, None)
            tag_hidden = (tag_filter == 1 and is_tagged) or (tag_filter == 2 and not is_tagged)
            item_value_type = list_item.data(Qt.UserRole + 4)
            type_hidden = bool(type_filter_value) and item_value_type != type_filter_value
            amp_hidden = False
            if amp_enabled:
                item_min = list_item.data(Qt.UserRole + 1)
                item_max = list_item.data(Qt.UserRole + 2)
                if item_min is not None and item_max is not None:
                    amp_hidden = item_min < fmin or item_max > fmax
            frames_hidden = False
            if frames_enabled:
                item_frames = list_item.data(Qt.UserRole + 3)
                if item_frames is not None:
                    frames_hidden = item_frames < self._frames_filter_min or item_frames > self._frames_filter_max
            time_hidden = not self._candidate_passes_time_filter(row)
            item_score = list_item.data(Qt.UserRole + 5)
            score_hidden = min_score > 0.0 and item_score is not None and item_score < min_score
            item_byte_order = list_item.data(Qt.UserRole + 6)
            endianness_hidden = self._endianness_filter != "All" and item_byte_order != self._endianness_filter
            item_signal_length = list_item.data(Qt.UserRole + 7)
            length_hidden = (
                self._min_length_filter > 0
                and item_signal_length is not None
                and item_signal_length < self._min_length_filter
            )
            fragment_hidden = hide_fragments and bool(list_item.data(Qt.UserRole + 9))
            item_category = list_item.data(Qt.UserRole + 10)
            category_hidden = bool(category_filter_value) and item_category != category_filter_value
            list_item.setHidden(
                tag_hidden or type_hidden or amp_hidden or frames_hidden or time_hidden
                or score_hidden or endianness_hidden or length_hidden or fragment_hidden or category_hidden
            )
        total_count = self.candidate_list.count()
        visible_count = sum(
            1
            for row in range(total_count)
            if self.candidate_list.item(row) is not None and not self.candidate_list.item(row).isHidden()
        )
        self._score_filter_count_label.setText(
            get_text("candidate_score_filter_count").format(visible=visible_count, total=total_count)
        )
        self._score_filter_count_label.setStyleSheet(f"color: {get_active_theme().accent}; font-weight: 600;")
        has_candidates = total_count > 0
        self._candidate_stack.setCurrentWidget(self.candidate_list if visible_count else self._candidate_empty)
        self._candidate_empty.setText(
            get_text("candidate_interpretations_empty_filtered")
            if has_candidates
            else get_text("candidate_interpretations_empty_candidates")
        )
        self._ensure_visible_candidate_selection()
        self._on_visible_candidates_changed()

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
        if row < 0 or row >= len(self._displayed_items):
            return False
        if self._visual_ts_min is None and self._visual_ts_max is None:
            return True
        item = self._displayed_items[row]
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
            "Category": _category_display_name(candidate.signal_category),
            "Frames": candidate.frames,
            "Frames in Filter": len(x),
            "Changes": candidate.changes,
            "Distinct Values": candidate.distinct_values,
            "Score": f"{candidate.score:.3f}",
            "Min": "" if candidate.min_value is None else self._format_number(candidate.min_value),
            "Max": "" if candidate.max_value is None else self._format_number(candidate.max_value),
            "Sample Values": ", ".join(candidate.sample_values),
        }
        if candidate.multi_byte_hint:
            details["Multi-byte Hint"] = candidate.multi_byte_hint
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
        lines = ["# Canlytics Signal Tags", "# Format: signal_label = tag_name", ""]
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



