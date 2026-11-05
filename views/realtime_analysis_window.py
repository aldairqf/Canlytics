from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QAbstractItemView,
    QFrame,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSplitter,
    QSpinBox,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from config.defaults import REAL_TIME_ANALYSIS_COLUMNS
from config.app_config import get_text
from config.theme import get_active_theme
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.real_time_analysis_viewmodel import RealTimeAnalysisViewModel
from viewmodels.table_filter_viewmodel import TableFilterViewModel
from viewmodels.table_model import TableModel
from viewmodels.table_viewmodel import TableViewModel
from views.icons import icon
from views.settings.mux_configuration_dialog import edit_mux_configuration
from views.table.row_height_manager import RowHeightManager
from views.table.ts_display_delegate import TsDisplayDelegate
from views.table.data_bytes_highlight_delegate import DataBytesHighlightDelegate
from views.table.table_view import DataTableView
from views.widgets.can_id_panel import CanIdPanelWidget
from viewmodels.dbc_manager_viewmodel import DbcManagerViewModel
from utils.timezone_format import format_timestamp


class RealTimeAnalysisWindow(QMainWindow):
    def __init__(
        self,
        analysis_vm: RealTimeAnalysisViewModel,
        dbc_manager: DbcManagerViewModel,
        *,
        time_config_vm,
        timezone_mode: str = "none",
        parent=None,
        range_diff_manager=None,
        mux_configuration_vm=None,
        time_cursor_vm=None,
        event_markers_vm=None,
        offline_mode: bool = False,
    ):
        super().__init__(parent)
        self._range_diff_manager = range_diff_manager
        self._mux_configuration_vm = mux_configuration_vm
        self._time_cursor_vm = time_cursor_vm
        self._event_markers_vm = event_markers_vm
        self._applying_global_cursor = False
        self._offline_mode = bool(offline_mode)
        self._offline_slider_pressed = False
        self._event_marker_timestamps = {
            marker.timestamp for marker in event_markers_vm.markers
        } if event_markers_vm is not None else set()
        # Without this, close() only hides the window: RealTimeAnalysisWindowManager
        # (a BaseWindowManager singleton) relies on the destroyed signal to reset its
        # _window reference, so it would otherwise report this window as still open
        # forever after the first close, and reopening would just re-show the same
        # stale instance instead of building a fresh one.
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("real_time_analysis_label"))
        self.resize(1100, 700)

        self._analysis_vm = analysis_vm
        self._time_vm = time_config_vm
        self._timezone_mode = (timezone_mode or "none").strip() or "none"
        self._filter_vm = TableFilterViewModel()
        self._pending_scope: set[str] = set()
        self._listed_ids: set[str] = set()
        self._filter_vm.set_real_time_analysis(True)

        self._table_model = TableModel(REAL_TIME_ANALYSIS_COLUMNS, optimize_append=False)
        self._table_model.set_row_background_provider(self._event_marker_row_background)
        self._table_vm = TableViewModel(self._table_model)
        self._interpret_vm = InterpretationViewModel(dbc_manager, self._table_vm, parent=self)
        self._data_delegate = DataBytesHighlightDelegate(self)
        self._ts_delegate = TsDisplayDelegate(self._timezone_mode, parent=self)

        self.table = DataTableView(self._table_model)
        self.table.setItemDelegateForColumn(REAL_TIME_ANALYSIS_COLUMNS.index("DATA"), self._data_delegate)
        self.table.setItemDelegateForColumn(REAL_TIME_ANALYSIS_COLUMNS.index("TS"), self._ts_delegate)
        self._table_model.set_row_foreground_provider(self._row_foreground_for_changes_only)
        self.panel = CanIdPanelWidget(
            dbc_manager.resolve_message_name,
            self._interpret_vm,
            show_interpret_controls=False,
            parent=self,
        )
        self.row_heights = RowHeightManager(self.table, self._table_model, self._table_vm)
        self._selected_ids: set[str] = set()
        self._details_can_id: str | None = None
        self._details_row: dict | None = None
        self._details_signature: str = ""

        self.show_only_changing = QCheckBox(get_text("show_only_changing_label"))
        self.show_only_changing.setChecked(self._analysis_vm.show_only_changing)
        self.detect_changes = QCheckBox(get_text("real_time_detect_changes_label"))
        self.detect_changes.setChecked(self._analysis_vm.detect_changes)
        self.show_bits = QCheckBox(get_text("real_time_show_bits_label"))
        self.show_bits.setChecked(False)
        self.refresh_interval = QSpinBox(self)
        self.refresh_interval.setRange(10, 5000)
        self.refresh_interval.setSingleStep(10)
        self.refresh_interval.setSuffix(" ms")
        self.refresh_interval.setValue(self._analysis_vm.refresh_interval_ms)
        self.highlight_hold = QSpinBox(self)
        self.highlight_hold.setRange(100, 10000)
        self.highlight_hold.setSingleStep(100)
        self.highlight_hold.setSuffix(" ms")
        self.highlight_hold.setValue(self._analysis_vm.highlight_hold_ms)
        self.options_button = QToolButton(self)
        self.options_button.setText(get_text("realtime_options_button"))
        self.options_button.setIcon(icon("settings"))
        self.options_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.options_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.options_menu = QMenu(self.options_button)
        options_panel = QWidget(self.options_menu)
        options_form = QFormLayout(options_panel)
        options_form.setContentsMargins(8, 6, 8, 6)
        options_form.addRow(QLabel(get_text("real_time_refresh_interval_label")), self.refresh_interval)
        options_form.addRow(QLabel(get_text("realtime_highlight_hold_label")), self.highlight_hold)
        options_action = QWidgetAction(self.options_menu)
        options_action.setDefaultWidget(options_panel)
        self.options_menu.addAction(options_action)
        self.options_button.setMenu(self.options_menu)
        self.mux_summary = QLabel(self._analysis_vm.mux_configuration_summary())
        self.change_summary = QLabel("")
        self.btn_mux_configuration = QPushButton(get_text("mux_configuration_button"))
        self.btn_reset = QPushButton(get_text("reset_change_detection"))
        self.btn_reset.setToolTip(get_text("reset_change_detection_tooltip"))
        self.btn_compare_from_now = QPushButton(icon("git-compare"), get_text("realtime_compare_from_now"), self)
        self.btn_compare_from_now.setToolTip(get_text("realtime_compare_from_now_tooltip"))
        self.btn_compare_from_now.setVisible(self._range_diff_manager is not None)
        self.status = QLabel(get_text("connection_status_idle"))
        self.offline_transport = QWidget(self)
        transport_layout = QHBoxLayout(self.offline_transport)
        transport_layout.setContentsMargins(0, 0, 0, 0)
        self.offline_previous = QPushButton(get_text("realtime_offline_previous"), self.offline_transport)
        self.offline_play = QPushButton(get_text("realtime_offline_play"), self.offline_transport)
        self.offline_play.setCheckable(True)
        self.offline_next = QPushButton(get_text("realtime_offline_next"), self.offline_transport)
        self.offline_position = QSlider(Qt.Horizontal, self.offline_transport)
        self.offline_position.setRange(0, 0)
        self.offline_position.setMinimumWidth(180)
        transport_layout.addWidget(self.offline_previous)
        transport_layout.addWidget(self.offline_play)
        transport_layout.addWidget(self.offline_position, 1)
        transport_layout.addWidget(self.offline_next)
        self.offline_transport.setVisible(self._offline_mode)
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(50)
        self._playback_timer.timeout.connect(self._advance_offline)
        self.details_card = QFrame(self)
        self.details_card.setFrameShape(QFrame.StyledPanel)
        self.details_id = QLabel(get_text("realtime_details_id_placeholder"), self.details_card)
        self.details_subtitle = QLabel("", self.details_card)
        self.details_frame = QLabel("", self.details_card)
        self.details_unique = self._make_details_table(self.details_card)
        card_layout = QVBoxLayout(self.details_card)
        card_layout.addWidget(self.details_id)
        card_layout.addWidget(self.details_subtitle)
        card_layout.addWidget(self.details_frame)
        card_layout.addWidget(QLabel(get_text("realtime_unique_values_per_byte"), self.details_card))
        card_layout.addWidget(self.details_unique)

        controls = QWidget(self)
        controls_layout = QHBoxLayout(controls)
        controls_layout.addWidget(self.detect_changes)
        controls_layout.addWidget(self.show_only_changing)
        controls_layout.addWidget(self.btn_reset)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.show_bits)
        controls_layout.addWidget(self.options_button)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.btn_mux_configuration)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.btn_compare_from_now)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.change_summary)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self.mux_summary)

        body = QSplitter(self)
        body.setOrientation(Qt.Horizontal)
        side = QWidget(self)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        details_header = QHBoxLayout()
        details_header.addWidget(QLabel(get_text("realtime_details_label")))
        details_header.addStretch(1)
        self.btn_clear_details_selection = QPushButton(get_text("realtime_clear_details_selection"), self)
        self.btn_clear_details_selection.setToolTip(get_text("realtime_clear_details_selection_tooltip"))
        details_header.addWidget(self.btn_clear_details_selection)
        side_layout.addLayout(details_header)
        side_layout.addWidget(self.details_card, 2)
        side_layout.addWidget(self.panel, 3)
        body.addWidget(self.table)
        body.addWidget(side)
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 1)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(controls)
        layout.addWidget(self.offline_transport)
        layout.addWidget(body, 1)
        self.setCentralWidget(central)
        self.statusBar().addPermanentWidget(self.status, 1)
        self._time_cursor_status = QLabel(self)
        self.statusBar().addPermanentWidget(self._time_cursor_status)
        self._hide_realtime_columns()
        self._resize_timestamp_column()

        self._filter_vm.dataframe_changed.connect(self._table_vm.set_dataframe)
        self._filter_vm.can_ids_changed.connect(self.panel.set_can_ids)
        self._filter_vm.can_ids_changed.connect(self._apply_pending_scope)
        self.panel.selected_ids_changed.connect(self._on_selected_ids_changed)
        self.table.pressed.connect(self._on_table_interaction)
        self.table.clicked.connect(self._on_table_interaction)
        self.table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self._on_table_interaction(current)
        )
        self.btn_clear_details_selection.clicked.connect(self._clear_details_selection)

        self.detect_changes.toggled.connect(self._analysis_vm.set_detect_changes)
        self.show_only_changing.toggled.connect(self._analysis_vm.set_show_only_changing)
        self.show_bits.toggled.connect(self._on_show_bits_toggled)
        self.refresh_interval.valueChanged.connect(self._analysis_vm.set_refresh_interval_ms)
        self.highlight_hold.valueChanged.connect(self._analysis_vm.set_highlight_hold_ms)
        self.btn_mux_configuration.clicked.connect(self._open_mux_configuration)
        self.btn_reset.clicked.connect(self._analysis_vm.reset_realtime_state)
        self.btn_compare_from_now.clicked.connect(self._on_compare_from_now)
        self.offline_previous.clicked.connect(lambda: self._step_offline(-1))
        self.offline_next.clicked.connect(lambda: self._step_offline(1))
        self.offline_play.toggled.connect(self._on_play_toggled)
        self.offline_position.sliderPressed.connect(self._on_offline_slider_pressed)
        self.offline_position.sliderReleased.connect(self._on_offline_slider_released)
        self.offline_position.valueChanged.connect(self._seek_offline)
        # The VM outlives this window, so every VM -> window connection is undone in closeEvent.
        self._vm_connections = [
            (self._time_vm.timezone_changed, self._on_timezone_changed),
            (self._analysis_vm.dataframe_changed, self._filter_vm.set_live_dataframe),
            (self._analysis_vm.dataframe_changed, self._on_live_dataframe_changed),
            (self._analysis_vm.mux_configuration_changed, self._refresh_mux_summary),
            (self._analysis_vm.change_summary_changed, self.change_summary.setText),
            (self._analysis_vm.detect_changes_changed, self._on_detect_changes_changed),
            (self._analysis_vm.refresh_interval_changed, self._on_refresh_interval_changed),
            (self._analysis_vm.highlight_hold_changed, self._on_highlight_hold_changed),
            (self._analysis_vm.show_only_changing_changed, self._on_show_only_changing_changed),
            (self._analysis_vm.show_only_changing_changed, self._repaint_table),
            (self._analysis_vm.offline_index_ready, self._on_offline_index_ready),
            (self._analysis_vm.offline_index_failed, self._on_offline_index_failed),
            (self._analysis_vm.offline_index_started, self._on_offline_index_started),
        ]
        for signal, slot in self._vm_connections:
            signal.connect(slot)
        if self._time_cursor_vm is not None:
            self._time_cursor_vm.cursor_changed.connect(self._apply_global_cursor)
            if self._time_cursor_vm.timestamp is not None:
                self._apply_global_cursor(self._time_cursor_vm.timestamp, "initial")
        if self._event_markers_vm is not None:
            self._event_markers_vm.markers_changed.connect(self._refresh_event_marker_rows)

        self._filter_vm.set_live_dataframe(getattr(self._analysis_vm, "_df"))
        self._on_detect_changes_changed(self._analysis_vm.detect_changes)
        self.set_offline_mode(self._offline_mode)
        if self._offline_mode and self._analysis_vm.offline_frame_count:
            self._on_offline_index_ready(
                self._analysis_vm.offline_position_count,
                self._analysis_vm.offline_frame_index,
            )
        self._refresh_details()

    def _open_mux_configuration(self) -> None:
        if self._mux_configuration_vm is not None:
            edit_mux_configuration(self._mux_configuration_vm, self)
        self._refresh_mux_summary()

    def _on_compare_from_now(self) -> None:
        if self._range_diff_manager is not None:
            self._range_diff_manager.open_window_live(source=get_text("real_time_analysis_label"))

    def _refresh_mux_summary(self) -> None:
        self.mux_summary.setText(self._analysis_vm.mux_configuration_summary())

    def _on_interpret_enabled_changed(self, enabled: bool) -> None:
        self.panel.set_interpret_checked(enabled)
        self.panel.refresh_labels()
        self.row_heights.refresh()

    def _on_detect_changes_changed(self, enabled: bool) -> None:
        self.detect_changes.blockSignals(True)
        self.detect_changes.setChecked(enabled)
        self.detect_changes.blockSignals(False)
        self.show_only_changing.setEnabled(enabled)
        self.show_only_changing.setToolTip(
            get_text("show_only_changing_tooltip")
            if enabled
            else get_text("show_only_changing_disabled_tooltip")
        )
        if not enabled:
            self._on_show_only_changing_changed(False)

    def _on_show_only_changing_changed(self, enabled: bool) -> None:
        self.show_only_changing.blockSignals(True)
        self.show_only_changing.setChecked(enabled)
        self.show_only_changing.blockSignals(False)

    def _row_foreground_for_changes_only(self, row: int) -> QColor | None:
        # B-03: dim, don't hide -- rows stay in the table; the CAN ID panel's
        # checkboxes are the user's own manual selection, untouched by this.
        if self._offline_mode or not self._analysis_vm.show_only_changing:
            return None
        can_id = self._table_model.get_row_can_id(row)
        if can_id is None or can_id in self._analysis_vm.changed_ids:
            return None
        return QColor(get_active_theme().text_muted)

    def _on_show_bits_toggled(self, enabled: bool) -> None:
        self._table_model.set_data_display_mode("bits" if enabled else "bytes")

    def _on_selected_ids_changed(self, ids: set[str]) -> None:
        selected = {str(v).strip().upper() for v in (ids or set()) if str(v).strip()}
        self._selected_ids = selected
        self._filter_vm.set_selected_ids(selected)
        self._table_model.rebuild_timestamp_index()
        self._refresh_details()

    def _on_table_interaction(self, index) -> None:
        if not index.isValid():
            return
        row_record = self._table_model.get_row_record(index.row())
        self._details_row = dict(row_record) if isinstance(row_record, dict) else None
        can_id = self._table_model.get_row_can_id(index.row())
        self._details_can_id = (str(can_id).strip().upper() if can_id is not None else None)
        self._refresh_details()
        if self._time_cursor_vm is not None and isinstance(row_record, dict) and not self._applying_global_cursor:
            self._time_cursor_vm.set_timestamp(row_record.get("TS"), "realtime_table")

    def _apply_global_cursor(self, timestamp: float, source: str) -> None:
        self._time_cursor_status.setText(
            get_text("global_time_cursor_status").format(
                timestamp=format_timestamp(timestamp, self._timezone_mode)
            )
        )
        if self._offline_mode:
            self._analysis_vm.set_offline_timestamp(timestamp)
            self._sync_offline_slider(timestamp)
        if source == "realtime_table":
            return
        row = self._table_model.nearest_row_for_timestamp(timestamp)
        if row is not None:
            self._applying_global_cursor = True
            try:
                self.table.setCurrentIndex(self._table_model.index(row, 0))
                self.table.selectRow(row)
                self.table.scrollTo(
                    self._table_model.index(row, REAL_TIME_ANALYSIS_COLUMNS.index("TS")),
                    QAbstractItemView.PositionAtCenter,
                )
            finally:
                self._applying_global_cursor = False

    def set_offline_mode(self, enabled: bool) -> None:
        self._offline_mode = bool(enabled)
        self.offline_transport.setVisible(self._offline_mode)
        self.options_button.setEnabled(not self._offline_mode)
        self.btn_compare_from_now.setVisible(
            self._range_diff_manager is not None and not self._offline_mode
        )
        if not self._offline_mode:
            self._stop_playback()
            self.status.setText(get_text("connection_status_idle"))
            self.detect_changes.setEnabled(True)
            self.btn_reset.setEnabled(True)
            self._on_detect_changes_changed(self._analysis_vm.detect_changes)
            self.change_summary.setText(self._analysis_vm.change_summary)
        else:
            self.status.setText(get_text("realtime_offline_indexing"))
            self.detect_changes.setEnabled(False)
            self.show_only_changing.setEnabled(False)
            self.btn_reset.setEnabled(False)
            self.change_summary.setText(get_text("realtime_offline_changes_unavailable"))
            self.offline_position.setEnabled(False)
            self.offline_previous.setEnabled(False)
            self.offline_next.setEnabled(False)
            self.offline_play.setEnabled(False)

    def _on_offline_index_ready(self, count: int, frame_index: int) -> None:
        if not self._offline_mode:
            return
        self.offline_position.blockSignals(True)
        self.offline_position.setRange(0, max(0, int(count) - 1))
        self.offline_position.setEnabled(count > 0)
        self.offline_previous.setEnabled(count > 0)
        self.offline_next.setEnabled(count > 0)
        self.offline_play.setEnabled(count > 1)
        self.offline_position.setValue(max(0, int(frame_index)))
        self.offline_position.blockSignals(False)
        self.status.setText(get_text("connection_status_idle"))
        if count <= 0:
            return
        timestamp = self._time_cursor_vm.timestamp if self._time_cursor_vm is not None else None
        if timestamp is None:
            timestamp = self._analysis_vm.offline_timestamp_at(0)
            if timestamp is not None and self._time_cursor_vm is not None:
                self._time_cursor_vm.set_timestamp(timestamp, "realtime_transport")
            elif timestamp is not None:
                self._analysis_vm.set_offline_timestamp(timestamp)
        else:
            self._apply_global_cursor(timestamp, "offline_index_ready")

    def _on_offline_index_failed(self, message: str) -> None:
        self.status.setText(get_text("realtime_offline_index_error").format(error=message))
        self.offline_position.setEnabled(False)
        self.offline_previous.setEnabled(False)
        self.offline_next.setEnabled(False)
        self.offline_play.setEnabled(False)

    def _on_offline_index_started(self) -> None:
        if self._offline_mode:
            self.status.setText(get_text("realtime_offline_indexing"))
            self.offline_position.setEnabled(False)
            self.offline_previous.setEnabled(False)
            self.offline_next.setEnabled(False)
            self.offline_play.setEnabled(False)

    def _sync_offline_slider(self, timestamp: float) -> None:
        if not self._offline_mode or not self._analysis_vm.offline_position_count:
            return
        index = self._analysis_vm.offline_index_at(timestamp)
        self.offline_position.blockSignals(True)
        self.offline_position.setValue(index)
        self.offline_position.blockSignals(False)

    def _on_offline_slider_pressed(self) -> None:
        self._offline_slider_pressed = True
        self._stop_playback()

    def _on_offline_slider_released(self) -> None:
        self._offline_slider_pressed = False
        self._seek_offline(self.offline_position.value())

    def _seek_offline(self, frame_index: int) -> None:
        if not self._offline_mode:
            return
        timestamp = self._analysis_vm.offline_timestamp_at(frame_index)
        if timestamp is None:
            return
        if self._time_cursor_vm is not None:
            self._time_cursor_vm.set_timestamp(timestamp, "realtime_transport")
        else:
            self._analysis_vm.set_offline_timestamp(timestamp)

    def _step_offline(self, direction: int) -> None:
        count = self._analysis_vm.offline_position_count
        if not self._offline_mode or count <= 0:
            return
        current = self._analysis_vm.offline_frame_index
        if current < 0:
            target = 0
        else:
            target = max(0, min(count - 1, current + int(direction)))
        self._seek_offline(target)

    def _on_play_toggled(self, playing: bool) -> None:
        if playing:
            self.offline_play.setText(get_text("realtime_offline_pause"))
            self._playback_timer.start()
        else:
            self._playback_timer.stop()
            self.offline_play.setText(get_text("realtime_offline_play"))

    def _advance_offline(self) -> None:
        if not self._offline_mode:
            self._stop_playback()
            return
        if self._analysis_vm.offline_frame_index >= self._analysis_vm.offline_position_count - 1:
            self._stop_playback()
            return
        self._step_offline(1)

    def _stop_playback(self) -> None:
        self._playback_timer.stop()
        self.offline_play.blockSignals(True)
        self.offline_play.setChecked(False)
        self.offline_play.blockSignals(False)
        self.offline_play.setText(get_text("realtime_offline_play"))

    def _event_marker_row_background(self, row: int):
        record = self._table_model.get_row_record(row)
        if record is None or record.get("TS") not in self._event_marker_timestamps:
            return None
        return QColor(get_active_theme().accent)

    def _refresh_event_marker_rows(self, markers) -> None:
        self._event_marker_timestamps = {marker.timestamp for marker in markers}
        self.table.viewport().update()

    def _clear_details_selection(self) -> None:
        # BUGS.md B-06: without this, _details_row stays truthy forever after the
        # first table click, and checking/unchecking CAN IDs in the panel stops
        # having any visible effect on this panel for the rest of the session.
        self._details_row = None
        self._details_can_id = None
        self._refresh_details()

    def _refresh_details(self) -> None:
        data = None
        if self._details_row:
            data = self._analysis_vm.details_data_for_row(self._details_row)
        elif self._details_can_id:
            data = self._analysis_vm.details_data_for_selection([self._details_can_id])
        else:
            data = self._analysis_vm.details_data_for_selection(self._selected_ids)
        signature = repr(data)
        if signature == self._details_signature:
            return
        self._details_signature = signature
        self._render_details(data)

    def _render_details(self, data: dict) -> None:
        if data.get("empty"):
            self.details_id.setText(get_text("realtime_details_id_placeholder"))
            self.details_subtitle.setText(data.get("empty", ""))
            self.details_frame.setText("")
            self._fill_details_table(self.details_unique, ["-"] * 8)
            return

        self.details_id.setText(get_text("realtime_details_id_prefix").format(id=data.get('id', '-')))
        self.details_subtitle.setText(str(data.get("subtitle", "") or ""))
        frame = data.get("frame", {})
        self.details_frame.setText(get_text("realtime_period_stats").format(
            minimum=frame.get("min", "-"), maximum=frame.get("max", "-"),
            average=frame.get("avg", "-"), count=frame.get("n", "-"),
        ))
        self._fill_details_table(self.details_unique, list(data.get("unique", ["-"] * 8)))

    def _make_details_table(self, parent: QWidget) -> QTableWidget:
        table = QTableWidget(1, 8, parent)
        table.setHorizontalHeaderLabels([f"B{i}" for i in range(8)])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFixedHeight(
            table.horizontalHeader().sizeHint().height()
            + table.verticalHeader().defaultSectionSize()
            + 2 * table.frameWidth()
        )
        return table

    def _hide_realtime_columns(self) -> None:
        for name in ("Bus",):
            if name not in self._table_model._columns:
                continue
            col = self._table_model._columns.index(name)
            self.table.setColumnHidden(col, True)

    def _fill_details_table(self, table: QTableWidget, values: list[str]) -> None:
        table.blockSignals(True)
        for col in range(8):
            table.setItem(0, col, QTableWidgetItem(str(values[col] if col < len(values) else "-")))
        table.blockSignals(False)

    def _on_refresh_interval_changed(self, interval_ms: int) -> None:
        self.refresh_interval.blockSignals(True)
        self.refresh_interval.setValue(int(interval_ms))
        self.refresh_interval.blockSignals(False)

    def _on_highlight_hold_changed(self, hold_ms: int) -> None:
        self.highlight_hold.blockSignals(True)
        self.highlight_hold.setValue(int(hold_ms))
        self.highlight_hold.blockSignals(False)

    def set_checked_can_ids(self, can_ids: set[str]) -> None:
        """P1 handoff entry point (e.g. Candidate Interpretations' "Confirm in
        Real-Time"): scope the CAN ID panel to exactly these ids."""
        # A freshly opened window has no ids yet; keep re-applying the scope until they arrive.
        self._pending_scope = {str(v).strip().upper() for v in can_ids}
        self._apply_pending_scope(self._listed_ids)

    def _apply_pending_scope(self, ids) -> None:
        self._listed_ids = {str(v).strip().upper() for v in ids}
        if not self._pending_scope:
            return
        self.panel.set_checked_ids(self._pending_scope)
        if self._pending_scope <= self._listed_ids:
            self._pending_scope = set()

    def _on_live_dataframe_changed(self, _df) -> None:
        self._refresh_details()

    def _repaint_table(self, _enabled: bool) -> None:
        self.table.viewport().update()

    def _on_timezone_changed(self, timezone_mode: str) -> None:
        self._timezone_mode = (timezone_mode or "none").strip() or "none"
        self._ts_delegate.set_timezone_mode(self._timezone_mode)
        self._resize_timestamp_column()
        self.table.viewport().update()

    def _resize_timestamp_column(self) -> None:
        column = REAL_TIME_ANALYSIS_COLUMNS.index("TS")
        sample = self._ts_delegate.displayText(0.0, self.table.locale())
        width = self.table.fontMetrics().horizontalAdvance(sample)
        section_width = self.table.horizontalHeader().sectionSizeHint(column)
        self.table.setColumnWidth(column, max(width + 16, section_width))

    def _disconnect_vm(self) -> None:
        for signal, slot in self._vm_connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._vm_connections = []

    def closeEvent(self, event) -> None:
        self._stop_playback()
        self._disconnect_vm()
        if self._time_cursor_vm is not None:
            try:
                self._time_cursor_vm.cursor_changed.disconnect(self._apply_global_cursor)
            except (TypeError, RuntimeError):
                pass
        if self._event_markers_vm is not None:
            try:
                self._event_markers_vm.markers_changed.disconnect(self._refresh_event_marker_rows)
            except (TypeError, RuntimeError):
                pass
        self._interpret_vm.shutdown()
        super().closeEvent(event)
