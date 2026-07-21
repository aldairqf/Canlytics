from __future__ import annotations

from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from config.theme import get_active_theme
from models.frame_selector import FrameSelector
from models.signal import Signal
from services.range_diff import (
    ChangeType,
    DiffOptions,
    IdDiff,
    export_range_diff_csv,
    format_byte_values,
)
from utils.can_id import can_id_sort_key
from utils.timezone_format import format_timestamp
from viewmodels.range_diff_viewmodel import RangeDiffViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from viewmodels.view_signal import ViewSignal
from views.icons import icon
from views.plot.add_to_plot_menu import make_view_signal
from views.plot.time_axis import TimeAxisItem
from views.widgets.eta_progress_dialog import EtaProgressDialog
from views.widgets.range_timeline import RangeTimeline

if TYPE_CHECKING:
    from services.session_state import SessionStateStore
    from views.plot.plot_window_manager import PlotWindowManager

_FILTER_PREFS_KEY = "range_diff"

_COLUMN_KEYS = [
    "range_diff_col_id_byte", "range_diff_col_presence", "range_diff_col_a",
    "range_diff_col_b", "range_diff_col_len_changed", "range_diff_col_type",
    "range_diff_col_signal", "range_diff_col_multi_byte", "range_diff_col_delta_mean",
    "range_diff_col_p_value", "range_diff_col_frames",
]
(
    _COL_ID_BYTE, _COL_PRESENCE, _COL_A, _COL_B, _COL_LEN_CHANGED, _COL_TYPE, _COL_SIGNAL,
    _COL_MULTI_BYTE, _COL_DELTA_MEAN, _COL_P_VALUE, _COL_FRAMES,
) = range(11)
_PRESENCE_KEYS = {
    "both": "range_diff_presence_both",
    "only_a": "range_diff_presence_only_a",
    "only_b": "range_diff_presence_only_b",
}
_TYPE_KEYS = {
    ChangeType.CONST_SHIFT: "range_diff_type_const_shift",
    ChangeType.NEW_TERRITORY: "range_diff_type_new_territory",
    ChangeType.RANGE_SHIFT: "range_diff_type_range_shift",
    ChangeType.SAME_OSCILLATION: "range_diff_type_same_oscillation",
}


def _type_color(theme, change_type: ChangeType) -> str | None:
    return {
        ChangeType.CONST_SHIFT: theme.accent,
        ChangeType.NEW_TERRITORY: theme.warn,
        ChangeType.RANGE_SHIFT: theme.warn,
        ChangeType.SAME_OSCILLATION: theme.text_muted,
    }.get(change_type)


_SORT_KEY_ROLE = Qt.UserRole + 10  # B-14: numeric/CAN-ID sort key, text columns fall back to text compare


class _RangeDiffTreeItem(QTreeWidgetItem):
    """B-14: QTreeWidget's default sort compares column text -- wrong for Delta
    mean/p-value/Frames (numeric) and CAN ID (hex, not lexicographic). Columns with
    a _SORT_KEY_ROLE value sort by that instead."""

    def __lt__(self, other) -> bool:
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        self_key = self.data(column, _SORT_KEY_ROLE)
        other_key = other.data(column, _SORT_KEY_ROLE)
        if self_key is not None and other_key is not None:
            return self_key < other_key
        return super().__lt__(other)


class RangeDiffWindow(QMainWindow):
    def __init__(
        self,
        vm: RangeDiffViewModel,
        *,
        time_config_vm: TimeConfigViewModel,
        session_state: SessionStateStore | None = None,
        timezone_mode: str = "none",
        plot_manager: PlotWindowManager | None = None,
        candidate_interpretations_manager=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("range_diff_title"))
        self.resize(1100, 750)

        self._vm = vm
        self._time_vm = time_config_vm
        self._session_state = session_state
        self._timezone_mode = timezone_mode
        self._plot_manager = plot_manager
        self._candidate_interpretations_manager = candidate_interpretations_manager
        self._progress: EtaProgressDialog | None = None
        self._current_visible: list[IdDiff] = []
        self._current_range_a = None
        self._current_range_b = None
        self._current_plotted_byte: tuple[str, int] | None = None
        self._time_axis = TimeAxisItem(timezone_mode=self._timezone_mode, orientation="bottom")
        # B-15: built once per new report (_build_full_tree), reused across filter
        # toggles -- _apply_visibility only setHidden()s them, never rebuilds.
        self._built_top_items: dict[str, _RangeDiffTreeItem] = {}
        self._built_child_items: dict[str, dict[int, _RangeDiffTreeItem]] = {}

        self._build_ui()
        self._wire()
        self._restore_persisted_options()
        self._sync_options_from_vm()
        self.timeline.set_timezone(self._timezone_mode)
        self._vm.emit_current_state()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)

        ranges_group = QGroupBox(get_text("range_diff_ranges_group"), self)
        form = QFormLayout(ranges_group)
        # BUGS.md B-02: read-only -- fine selection happens via the timeline (B-01)
        # only. Editable text here used to round-trip through f"{value:g}" (6 sig
        # figs on an epoch ~1.78e9 = only ~10000s of precision), which silently
        # snapped a fine selection to a huge block on editingFinished.
        self.range_a_start = QLineEdit(self)
        self.range_a_start.setReadOnly(True)
        self.range_a_end = QLineEdit(self)
        self.range_a_end.setReadOnly(True)
        self.range_b_start = QLineEdit(self)
        self.range_b_start.setReadOnly(True)
        self.range_b_end = QLineEdit(self)
        self.range_b_end.setReadOnly(True)
        row_a = QHBoxLayout()
        row_a.addWidget(self.range_a_start)
        row_a.addWidget(self.range_a_end)
        row_b = QHBoxLayout()
        row_b.addWidget(self.range_b_start)
        row_b.addWidget(self.range_b_end)
        form.addRow(get_text("range_diff_range_a_label"), row_a)
        form.addRow(get_text("range_diff_range_b_label"), row_b)
        layout.addWidget(ranges_group)

        self.timeline = RangeTimeline(self)
        layout.addWidget(self.timeline)

        filters_row = QHBoxLayout()
        self.chk_same_oscillation = QCheckBox(get_text("range_diff_filter_same_oscillation"), self)
        self.chk_same_oscillation.setChecked(True)
        self.chk_same_oscillation.setToolTip(get_text("range_diff_filter_same_oscillation_tooltip"))
        self.chk_counters = QCheckBox(get_text("range_diff_filter_counters"), self)
        self.chk_counters.setChecked(True)
        self.chk_counters.setToolTip(get_text("range_diff_filter_counters_tooltip"))
        self.chk_new_territory_only = QCheckBox(get_text("range_diff_filter_new_territory_only"), self)
        self.chk_new_territory_only.setToolTip(get_text("range_diff_filter_new_territory_only_tooltip"))
        self.chk_presence = QCheckBox(get_text("range_diff_filter_presence"), self)
        self.chk_presence.setChecked(True)
        self.chk_presence.setToolTip(get_text("range_diff_filter_presence_tooltip"))
        self.chk_significance = QCheckBox(get_text("range_diff_filter_significance"), self)
        self.chk_significance.setToolTip(get_text("range_diff_filter_significance_tooltip"))
        self.min_frames_spin = QSpinBox(self)
        self.min_frames_spin.setRange(1, 1_000_000)
        self.min_frames_spin.setValue(3)
        self.btn_compare = QPushButton(get_text("range_diff_compare_button"), self)
        self.btn_compare.setObjectName("primary")
        self.btn_live = QPushButton(icon("radio"), get_text("range_diff_live_button"), self)
        self.btn_live.setCheckable(True)
        self.btn_live.setToolTip(get_text("range_diff_live_tooltip"))
        self.btn_export = QPushButton(icon("download"), get_text("range_diff_export_csv"), self)

        filters_row.addWidget(self.chk_same_oscillation)
        filters_row.addWidget(self.chk_counters)
        filters_row.addWidget(self.chk_new_territory_only)
        filters_row.addWidget(self.chk_presence)
        filters_row.addWidget(self.chk_significance)
        filters_row.addWidget(QLabel(get_text("range_diff_min_frames_label"), self))
        filters_row.addWidget(self.min_frames_spin)
        filters_row.addStretch(1)
        filters_row.addWidget(self.btn_export)
        filters_row.addWidget(self.btn_live)
        filters_row.addWidget(self.btn_compare)
        layout.addLayout(filters_row)

        self.live_status_label = QLabel(get_text("range_diff_live_status"), self)
        self.live_status_label.setVisible(False)
        layout.addWidget(self.live_status_label)

        self.status_label = QLabel(self)
        layout.addWidget(self.status_label)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(len(_COLUMN_KEYS))
        self.tree.setHeaderLabels([get_text(key) for key in _COLUMN_KEYS])
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setSortingEnabled(True)  # B-14
        layout.addWidget(self.tree, 1)

        self.empty_state = QLabel(get_text("range_diff_empty_state"), self)
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setWordWrap(True)
        layout.addWidget(self.empty_state)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(central, get_text("range_diff_tab_results"))
        self.tabs.addTab(self._build_plot_tab(), get_text("range_diff_tab_plot"))
        self.setCentralWidget(self.tabs)
        self._update_empty_state()

    def _build_plot_tab(self) -> QWidget:
        theme = get_active_theme()
        tab = QWidget(self)
        tl = QVBoxLayout(tab)

        self.plot_byte_label = QLabel(self)
        tl.addWidget(self.plot_byte_label)

        self.plot = pg.PlotWidget(tab, axisItems={"bottom": self._time_axis})
        self.plot.setLabel("left", "Value (Dec)")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot_curve = self.plot.plot([], [], pen=pg.mkPen(theme.accent, width=2))
        self._region_a = pg.LinearRegionItem(values=(0, 0), brush=pg.mkBrush(QColor(theme.accent).name() + "40"), movable=False)
        self._region_b = pg.LinearRegionItem(values=(0, 0), brush=pg.mkBrush(QColor(theme.error).name() + "40"), movable=False)
        self.plot.addItem(self._region_a)
        self.plot.addItem(self._region_b)
        tl.addWidget(self.plot, 1)

        self.plot_empty_state = QLabel(get_text("range_diff_plot_empty_state"), tab)
        self.plot_empty_state.setAlignment(Qt.AlignCenter)
        self.plot_empty_state.setWordWrap(True)
        tl.addWidget(self.plot_empty_state)
        self._update_plot_empty_state()
        return tab

    def _wire(self) -> None:
        self.btn_compare.clicked.connect(self._compare)
        self.btn_live.toggled.connect(self._on_live_toggled)
        self.btn_export.clicked.connect(self._export_csv)
        self.timeline.range_a_changed.connect(self._vm.set_range_a)
        self.timeline.range_b_changed.connect(self._vm.set_range_b)
        self._time_vm.timezone_changed.connect(self._set_timezone)
        for chk in (
            self.chk_same_oscillation,
            self.chk_counters,
            self.chk_new_territory_only,
            self.chk_presence,
            self.chk_significance,
        ):
            chk.toggled.connect(self._on_options_changed)
        self.min_frames_spin.valueChanged.connect(self._on_options_changed)
        self.tree.customContextMenuRequested.connect(self._open_plot_context_menu)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection_changed)

        self._vm.density_changed.connect(self._on_density)
        self._vm.ranges_changed.connect(self._on_ranges)
        self._vm.analysis_started.connect(self._on_started)
        self._vm.analysis_finished.connect(self._on_finished)
        self._vm.analysis_failed.connect(self._on_failed)
        self._vm.progress_changed.connect(self._on_progress)
        self._vm.visible_changed.connect(self._on_visible)
        self._vm.report_changed.connect(self._on_report)
        self._vm.live_active_changed.connect(self._on_live_active_changed)

    def _current_options(self) -> DiffOptions:
        return DiffOptions(
            ignore_same_oscillation=self.chk_same_oscillation.isChecked(),
            ignore_counters=self.chk_counters.isChecked(),
            only_new_territory=self.chk_new_territory_only.isChecked(),
            include_presence=self.chk_presence.isChecked(),
            min_frames=self.min_frames_spin.value(),
            require_significance=self.chk_significance.isChecked(),
        )

    def _on_options_changed(self, *_args) -> None:
        options = self._current_options()
        self._vm.set_options(options)
        if self._session_state is not None:
            self._session_state.set_window_prefs(_FILTER_PREFS_KEY, {
                "ignore_same_oscillation": options.ignore_same_oscillation,
                "ignore_counters": options.ignore_counters,
                "only_new_territory": options.only_new_territory,
                "include_presence": options.include_presence,
                "min_frames": options.min_frames,
                "require_significance": options.require_significance,
            })

    def _restore_persisted_options(self) -> None:
        # Only on a truly fresh VM (nobody touched the filters this app session
        # yet) -- BUGS.md B-13 already keeps the VM's in-session state correct
        # across this window's own close/reopen, this only fills in the gap of
        # a brand new app launch reverting to hardcoded defaults.
        if self._session_state is None or self._vm.options != DiffOptions():
            return
        prefs = self._session_state.get_window_prefs(_FILTER_PREFS_KEY)
        if not prefs:
            return
        self._vm.set_options(DiffOptions(
            ignore_same_oscillation=bool(prefs.get("ignore_same_oscillation", True)),
            ignore_counters=bool(prefs.get("ignore_counters", True)),
            only_new_territory=bool(prefs.get("only_new_territory", False)),
            include_presence=bool(prefs.get("include_presence", True)),
            min_frames=int(prefs.get("min_frames", 3)),
            require_significance=bool(prefs.get("require_significance", False)),
        ))

    def _sync_options_from_vm(self) -> None:
        # BUGS.md B-13: the vm is a long-lived singleton but this window is destroyed
        # and recreated on close/reopen -- without this, the checkboxes would show
        # construction defaults while the vm (and the filtered report) keeps the
        # options from before the window closed.
        opts = self._vm.options
        for checkbox, value in (
            (self.chk_same_oscillation, opts.ignore_same_oscillation),
            (self.chk_counters, opts.ignore_counters),
            (self.chk_new_territory_only, opts.only_new_territory),
            (self.chk_presence, opts.include_presence),
            (self.chk_significance, opts.require_significance),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)
        self.min_frames_spin.blockSignals(True)
        self.min_frames_spin.setValue(opts.min_frames)
        self.min_frames_spin.blockSignals(False)
        self._on_live_active_changed(self._vm.is_live)

    def _compare(self) -> None:
        if self._vm.running:
            return
        self._vm.set_options(self._current_options())
        self._vm.run()

    def _on_live_toggled(self, checked: bool) -> None:
        if checked:
            self._vm.capture_live_baseline()
        else:
            self._vm.stop_live()

    def _on_live_active_changed(self, active: bool) -> None:
        self.btn_live.blockSignals(True)
        self.btn_live.setChecked(active)
        self.btn_live.blockSignals(False)
        self.btn_compare.setEnabled(not active)
        self.timeline.setEnabled(not active)
        self.live_status_label.setVisible(active)

    def _on_report(self, report) -> None:
        # B-15: build the full (unfiltered) tree once per new report -- filter-only
        # changes go through visible_changed -> _apply_visibility (no rebuild).
        self._build_full_tree(report)
        if not self._vm.is_live:
            return
        self.range_a_start.setText(format_timestamp(report.range_a.start, self._timezone_mode))
        self.range_a_end.setText(format_timestamp(report.range_a.end, self._timezone_mode))
        self.range_b_start.setText(format_timestamp(report.range_b.start, self._timezone_mode))
        self.range_b_end.setText(
            format_timestamp(report.range_b.end, self._timezone_mode) + get_text("range_diff_live_suffix")
        )
        self.timeline.set_range_a(report.range_a.start, report.range_a.end)
        self.timeline.set_range_b(report.range_b.start, report.range_b.end)
        self._current_range_a, self._current_range_b = report.range_a, report.range_b
        self._update_plot_regions()
        if self._current_plotted_byte is not None:
            self._plot_byte(*self._current_plotted_byte)

    def _on_tree_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.UserRole)
        if not data or data[0] != "byte":
            return
        _, id_diff, byte_diff = data
        self._plot_byte(id_diff.can_id, byte_diff.byte_index)

    def _plot_byte(self, can_id: str, byte_index: int) -> None:
        ts, values = self._vm.get_byte_series(can_id, byte_index)
        self._current_plotted_byte = (can_id, byte_index)
        self._plot_curve.setData(ts, values)
        self.plot_byte_label.setText(f"{can_id} · B{byte_index}")
        self._update_plot_regions()
        self._update_plot_empty_state()

    def _update_plot_regions(self) -> None:
        if self._current_range_a is not None:
            self._region_a.setRegion((self._current_range_a.start, self._current_range_a.end))
        if self._current_range_b is not None:
            self._region_b.setRegion((self._current_range_b.start, self._current_range_b.end))

    def _update_plot_empty_state(self) -> None:
        has_data = self._current_plotted_byte is not None
        self.plot.setVisible(has_data)
        self.plot_byte_label.setVisible(has_data)
        self.plot_empty_state.setVisible(not has_data)

    def _set_timezone(self, tz: str) -> None:
        self._timezone_mode = (tz or "none").strip() or "none"
        self.timeline.set_timezone(self._timezone_mode)
        self._time_axis.set_timezone(self._timezone_mode)
        self._on_ranges((self._vm.range_a, self._vm.range_b))

    def _on_density(self, payload) -> None:
        edges, counts = payload
        self.timeline.set_density(edges, counts)

    def _on_ranges(self, payload) -> None:
        range_a, range_b = payload
        self.range_a_start.setText(format_timestamp(range_a.start, self._timezone_mode))
        self.range_a_end.setText(format_timestamp(range_a.end, self._timezone_mode))
        self.range_b_start.setText(format_timestamp(range_b.start, self._timezone_mode))
        self.range_b_end.setText(format_timestamp(range_b.end, self._timezone_mode))
        self.timeline.set_range_a(range_a.start, range_a.end)
        self.timeline.set_range_b(range_b.start, range_b.end)
        self._current_range_a, self._current_range_b = range_a, range_b
        self._update_plot_regions()

    def _on_started(self) -> None:
        self._progress = EtaProgressDialog(get_text("range_diff_loading"), get_text("cancel"), self)
        self._progress.setWindowTitle(get_text("range_diff_title"))
        self._progress.canceled.connect(self._vm.cancel)
        self._progress.start()
        self.btn_compare.setEnabled(False)

    def _on_progress(self, done: int, total: int) -> None:
        if self._progress is not None:
            self._progress.report_progress(done, total)

    def _on_finished(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self.btn_compare.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        QMessageBox.warning(self, get_text("range_diff_title"), message)

    def _make_id_row(self, id_diff: IdDiff) -> _RangeDiffTreeItem:
        top = _RangeDiffTreeItem(
            [
                id_diff.can_id,
                get_text(_PRESENCE_KEYS[id_diff.presence]),
                ",".join(str(v) for v in id_diff.len_a) or "-",
                ",".join(str(v) for v in id_diff.len_b) or "-",
                get_text("range_diff_len_changed") if id_diff.len_changed else "",  # B-20: own column
                "",  # Type is byte-level only (B-20)
                id_diff.dbc_hint or "",  # B-17: combined hint, visible column
                "",  # Multi-byte hint is byte-level only
                "",
                "",
                f"{id_diff.frames_a}/{id_diff.frames_b}",
            ]
        )
        top.setData(0, Qt.UserRole, ("id", id_diff))
        top.setData(_COL_ID_BYTE, _SORT_KEY_ROLE, can_id_sort_key(id_diff.can_id))
        top.setData(_COL_FRAMES, _SORT_KEY_ROLE, id_diff.frames_a + id_diff.frames_b)
        if id_diff.dbc_hint:
            top.setToolTip(_COL_SIGNAL, id_diff.dbc_hint)
        return top

    def _make_byte_row(self, id_diff: IdDiff, byte_diff, theme) -> _RangeDiffTreeItem:
        dbc_hint = self._vm.get_byte_dbc_hint(id_diff.can_id, byte_diff.byte_index)
        child = _RangeDiffTreeItem(
            [
                f"B{byte_diff.byte_index}",
                "",
                format_byte_values(byte_diff.a),
                format_byte_values(byte_diff.b),
                "",  # LEN changed is id-level only (B-20)
                get_text(_TYPE_KEYS.get(byte_diff.change_type, "")),
                dbc_hint or "",  # B-17: per-byte hint
                byte_diff.multi_byte_hint,  # P2.3: carry-alignment with the next byte
                f"{byte_diff.delta_mean:+.2f}",
                f"{byte_diff.p_value:.4g}" if byte_diff.p_value is not None else "-",
                f"{byte_diff.a.n_frames}/{byte_diff.b.n_frames}",
            ]
        )
        child.setData(0, Qt.UserRole, ("byte", id_diff, byte_diff))
        child.setData(_COL_ID_BYTE, _SORT_KEY_ROLE, byte_diff.byte_index)
        child.setData(_COL_DELTA_MEAN, _SORT_KEY_ROLE, byte_diff.delta_mean)
        child.setData(_COL_P_VALUE, _SORT_KEY_ROLE, byte_diff.p_value if byte_diff.p_value is not None else float("inf"))
        child.setData(_COL_FRAMES, _SORT_KEY_ROLE, byte_diff.a.n_frames + byte_diff.b.n_frames)
        if dbc_hint:
            child.setToolTip(_COL_SIGNAL, dbc_hint)
        if byte_diff.multi_byte_hint:
            child.setToolTip(_COL_MULTI_BYTE, byte_diff.multi_byte_hint)
        color = _type_color(theme, byte_diff.change_type)
        if color:
            for col in range(self.tree.columnCount()):
                child.setForeground(col, QColor(color))
        return child

    def _build_full_tree(self, report) -> None:
        # B-15: the expensive full rebuild -- only runs when the report itself is new
        # (a fresh "Compare"/Live tick), never on a pure filter-option toggle.
        theme = get_active_theme()
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self._built_top_items = {}
        self._built_child_items = {}
        for id_diff in report.ids:
            top = self._make_id_row(id_diff)
            self.tree.addTopLevelItem(top)
            self._built_top_items[id_diff.can_id] = top
            children: dict[int, _RangeDiffTreeItem] = {}
            for byte_diff in id_diff.byte_diffs:
                child = self._make_byte_row(id_diff, byte_diff, theme)
                top.addChild(child)
                children[byte_diff.byte_index] = child
            self._built_child_items[id_diff.can_id] = children
        self.tree.setSortingEnabled(True)
        self.tree.resizeColumnToContents(0)

    def _on_visible(self, items: list[IdDiff]) -> None:
        # B-15: cheap -- only toggles visibility of already-built rows, never rebuilds.
        self._current_visible = items
        visible_bytes: dict[str, set[int]] = {
            id_diff.can_id: {bd.byte_index for bd in id_diff.byte_diffs} for id_diff in items
        }
        for can_id, top in self._built_top_items.items():
            shown_bytes = visible_bytes.get(can_id)
            top.setHidden(shown_bytes is None)
            for byte_idx, child in self._built_child_items.get(can_id, {}).items():
                child.setHidden(shown_bytes is None or byte_idx not in shown_bytes)
            if shown_bytes is not None:
                top.setExpanded(bool(shown_bytes))
        self.status_label.setText(get_text("range_diff_status").format(count=len(items)))
        self._update_empty_state()

    def _update_empty_state(self) -> None:
        has_rows = bool(self._current_visible)
        self.tree.setVisible(has_rows)
        self.empty_state.setVisible(not has_rows)

    def _open_plot_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind = data[0]
        id_diff = data[1]

        menu = QMenu(self)
        add_new = add_last = None
        if kind == "byte" and self._plot_manager is not None:
            add_new = menu.addAction(get_text("add_new_graph"))
            add_last = menu.addAction(get_text("add_last_graph"))
        analyze_action = None
        if self._candidate_interpretations_manager is not None:
            if add_new is not None:
                menu.addSeparator()
            analyze_action = menu.addAction(get_text("range_diff_analyze_as_signal"))
        if menu.isEmpty():
            return

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action is None:
            return
        if action is analyze_action:
            self._candidate_interpretations_manager.open_window_for_can_id(
                id_diff.can_id, source=get_text("range_diff_title")
            )
        elif action in (add_new, add_last) and kind == "byte":
            _, _, byte_diff = data
            view_signal = self._build_byte_view_signal(id_diff.can_id, byte_diff.byte_index)
            self._plot_manager.add_view_signal(view_signal, use_last=(action is add_last))

    @staticmethod
    def _build_byte_view_signal(can_id: str, byte_index: int) -> ViewSignal:
        signal = Signal(
            name=f"{can_id}.B{byte_index}",
            can_id=can_id,
            start_bit=byte_index * 8,
            length=8,
            le=True,
            scale=1.0,
            offset=0.0,
            type_data="uint",
        )
        selector = FrameSelector(selected_id=can_id, mode="exact")
        return make_view_signal(signal, selector)

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, get_text("range_diff_export_csv_title"), "", "CSV (*.csv)")
        if not path:
            return
        try:
            export_range_diff_csv(self._current_visible, path)
        except OSError as exc:
            QMessageBox.critical(self, get_text("range_diff_title"), get_text("range_diff_export_failed").format(error=str(exc)))
            return
        QMessageBox.information(self, get_text("range_diff_title"), get_text("range_diff_export_succeeded").format(path=path))

    def closeEvent(self, event) -> None:
        self._vm.cancel_and_wait_batch()  # B-19: wait for an in-flight batch; never touches Live
        super().closeEvent(event)
