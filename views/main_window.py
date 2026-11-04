from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QMimeData, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QAbstractItemView, QDialog, QMainWindow, QFileDialog, QLabel, QMenu, QMessageBox, QProgressDialog, QWidget

from config.defaults import DEFAULT_COLUMNS
from services.app_logging import log_file_path
from viewmodels.main_window_viewmodel import (
    MainWindowViewModel, new_session_prompt_kind, unsaved_prompt_kind,
)
from views.candidate_interpretations_window_manager import CandidateInterpretationsWindowManager
from views.can_send_window_manager import CanSendWindowManager
from views.dbc.dbc_manager_dialog import DbcManagerDialog
from views.dbc.working_dbc_dialog import WorkingDbcDialog
from views.debug_log_window_manager import DebugLogWindowManager
from views.main_window_view import MainWindowView
from views.menu.main_menu_factory import build_main_menu
from views.analyze_data_window_manager import AnalyzeDataWindowManager
from views.plot.plot_window_manager import PlotWindowManager
from views.range_diff_window_manager import RangeDiffWindowManager
from views.realtime_analysis_window_manager import RealTimeAnalysisWindowManager
from views.signal_coverage_window_manager import SignalCoverageWindowManager
from views.bus_statistics_window_manager import BusStatisticsWindowManager
from views.settings.about_dialog import AboutDialog
from views.settings.plugins_dialog import PluginsDialog
from views.settings.connection_dialog import ConnectionDialog
from views.settings.log_timezone_dialog import LogTimezoneDialog
from views.table.decode_line_layout_delegate import DecodeLineLayoutDelegate
from views.table.frame_context_menu import show_frame_context_menu
from views.table.row_height_manager import RowHeightManager
from views.table.ts_display_delegate import TsDisplayDelegate
from views.settings.time_config_dialog import TimeConfigDialog
from views.settings.time_filter_dialog import TimeFilterDialog
from views.icons import clear_icon_cache
from views.widgets.eta_progress_dialog import EtaProgressDialog
from views.widgets.log_export_dialog import LogExportDialog
from views.widgets.can_id_jump_dialog import CanIdJumpDialog
from views.base_window_manager import enable_window_geometry_persistence
from views.widgets.save_signal_dialog import SaveSignalDialog
from views.widgets.ribbon_bar import RibbonBar, RibbonCallbacks
from config.app_config import get_option, get_text
from config.theme import DEFAULT_THEME, apply_theme, get_active_theme
from config.version import APP_VERSION
from models.analysis_context import AnalysisContext
from models.plugin import PluginRecord

if TYPE_CHECKING:
    from services.bus_statistics import BusStatisticsSnapshot


class DataChangeAction(str, Enum):
    CLEAR = "clear"
    LOAD = "load"
    CLOSE = "close"


class MainWindow(QMainWindow):
    def __init__(self, viewmodel: MainWindowViewModel):
        super().__init__()
        self.setWindowTitle(f"{get_text('main_window_title')}  v{APP_VERSION}")
        self.resize(1200, 700)
        self.setAcceptDrops(True)

        self.vm = viewmodel
        self._timezone_mode = self.vm.timezone_mode
        self._load_progress: QProgressDialog | None = None
        self._dbc_restore_progress: EtaProgressDialog | None = None
        self._connection_dialog: ConnectionDialog | None = None
        self._recent_logs_menu: QMenu | None = None
        self._save_signal_dialog: SaveSignalDialog | None = None
        self._working_dbc_dialog: WorkingDbcDialog | None = None
        self._plugin_windows: dict[str, QWidget] = {}

        self.view = MainWindowView(
            self.vm.table_model,
            dbc_manager=self.vm.dbc_manager,
            interpret_vm=self.vm.interpret_vm,
            parent=self,
        )
        self.setCentralWidget(self.view)

        self._ts_delegate = TsDisplayDelegate(self._timezone_mode, parent=self.view.table)
        self.view.table.setItemDelegateForColumn(DEFAULT_COLUMNS.index("TS"), self._ts_delegate)
        self._resize_timestamp_column()
        self._decode_layout_delegate = DecodeLineLayoutDelegate(parent=self.view.table)
        self.view.table.setItemDelegateForColumn(DEFAULT_COLUMNS.index("DATA"), self._decode_layout_delegate)

        self.row_heights = RowHeightManager(self.view.table, self.vm.table_model, self.vm.table_vm)
        # A full model reset (e.g. the CAN ID filter selection changing) clears
        # TableModel._expanded_rows since row identity isn't stable across it --
        # the view's per-row explicit heights need to follow suit, or a row that
        # inherits a stale custom height renders its (now different) decoded
        # line count squeezed/garbled into the wrong-sized row.
        self.vm.table_model.modelReset.connect(self.row_heights.refresh)
        self.plot_manager = PlotWindowManager(
            self,
            data_vm=self.vm.data_vm,
            dbc_manager=self.vm.dbc_manager,
            table_model=self.vm.table_model,
            get_timezone=lambda: self.vm.timezone_mode,
            interpret_enabled=lambda: self.vm.interpret_vm.enabled,
            time_config_vm=self.vm.time_config_vm,
            connection_vm=self.vm.connection_vm,
            session_state=self.vm.session_state,
            analysis_context_vm=self.vm.analysis_context_vm,
        )
        self.real_time_analysis_manager = RealTimeAnalysisWindowManager(
            analysis_vm=self.vm.real_time_analysis_vm,
            dbc_manager=self.vm.dbc_manager,
            time_config_vm=self.vm.time_config_vm,
            get_timezone=lambda: self.vm.timezone_mode,
            is_live=lambda: self.vm.connection_vm.running,
            mux_configuration_vm=self.vm.mux_configuration_vm,
            parent=self,
        )
        self.analyze_data_manager = AnalyzeDataWindowManager(
            vm=self.vm.analyze_data_vm,
            data_vm=self.vm.data_vm,
            connection_vm=self.vm.connection_vm,
            time_config_vm=self.vm.time_config_vm,
            get_timezone=lambda: self.vm.timezone_mode,
            mux_configuration_vm=self.vm.mux_configuration_vm,
            time_range_vm=self.vm.time_range_vm,
            interpret_vm=self.vm.interpret_vm,
            resolve_message_name=self.vm.dbc_manager.resolve_message_name,
            plot_manager=self.plot_manager,
            analysis_context_vm=self.vm.analysis_context_vm,
            real_time_analysis_manager=self.real_time_analysis_manager,
            parent=self,
        )
        self.candidate_interpretations_manager = CandidateInterpretationsWindowManager(
            vm=self.vm.candidate_interpretations_vm,
            data_vm=self.vm.data_vm,
            time_config_vm=self.vm.time_config_vm,
            session_state=self.vm.session_state,
            get_timezone=lambda: self.vm.timezone_mode,
            plot_manager=self.plot_manager,
            real_time_analysis_manager=self.real_time_analysis_manager,
            analysis_context_vm=self.vm.analysis_context_vm,
            mux_configuration_vm=self.vm.mux_configuration_vm,
            time_range_vm=self.vm.time_range_vm,
            interpret_vm=self.vm.interpret_vm,
            resolve_message_name=self.vm.dbc_manager.resolve_message_name,
        )
        self.signal_coverage_manager = SignalCoverageWindowManager(
            vm=self.vm.signal_coverage_vm,
            plot_manager=self.plot_manager,
            analysis_context_vm=self.vm.analysis_context_vm,
            is_live=lambda: self.vm.connection_vm.running,
        )
        self.bus_statistics_manager = BusStatisticsWindowManager(self.vm.bus_statistics_vm)
        self.range_diff_manager = RangeDiffWindowManager(
            vm=self.vm.range_diff_vm,
            time_config_vm=self.vm.time_config_vm,
            get_timezone=lambda: self.vm.timezone_mode,
            session_state=self.vm.session_state,
            plot_manager=self.plot_manager,
            candidate_interpretations_manager=self.candidate_interpretations_manager,
            mux_configuration_vm=self.vm.mux_configuration_vm,
            analysis_context_vm=self.vm.analysis_context_vm,
        )
        self.real_time_analysis_manager.set_range_diff_manager(self.range_diff_manager)
        self.vm.analysis_context_vm.send_requested.connect(self._route_analysis_context)
        self.can_send_manager = CanSendWindowManager(
            vm=self.vm.can_send_vm,
            dbc_manager=self.vm.dbc_manager,
        )
        self.debug_log_manager = DebugLogWindowManager(
            qt_log_handler=self.vm.qt_log_handler,
            log_path=log_file_path(self.vm.session_state.root),
            session_state=self.vm.session_state,
        )
        self.real_time_analysis_manager.set_frame_context_handler(self._show_frame_context_menu)
        for manager in (
            self.real_time_analysis_manager,
            self.analyze_data_manager,
            self.candidate_interpretations_manager,
            self.signal_coverage_manager,
            self.bus_statistics_manager,
            self.range_diff_manager,
            self.can_send_manager,
            self.debug_log_manager,
        ):
            manager.set_geometry_persistence(self.vm.session_state)

        self.view.panel.selected_ids_changed.connect(self.vm.filter_vm.set_selected_ids)
        self.view.panel.interpret_toggled.connect(self.vm.interpret_vm.set_enabled)

        self.view.panel.expand_all_clicked.connect(self._on_expand_all)
        self.view.panel.collapse_all_clicked.connect(self._on_collapse_all)

        self.vm.data_vm.can_ids_changed.connect(self.view.panel.set_can_ids)
        self._can_id_jump_shortcut = QShortcut(QKeySequence.Find, self)
        self._can_id_jump_shortcut.setContext(Qt.ApplicationShortcut)
        self._can_id_jump_shortcut.activated.connect(self._jump_to_can_id)

        self.vm.interpret_vm.enabled_changed.connect(self._on_interpret_enabled_changed)
        self.vm.interpret_vm.available_changed.connect(lambda _: self.view.panel.refresh_labels())

        self.view.table.decode_context_requested.connect(self.plot_manager.on_decode_context)
        self.view.table.frame_context_requested.connect(self._show_frame_context_menu)
        self.view.table.row_toggle_requested.connect(self.row_heights.toggle_row)

        self.vm.log_load_vm.load_started.connect(self._show_load_progress)
        self.vm.log_load_vm.load_finished.connect(self._hide_load_progress)
        self.vm.log_load_vm.load_failed.connect(self._set_load_failed_text)
        self.vm.normalize_applied.connect(self._on_normalize_applied)
        self.vm.normalize_failed.connect(self._on_normalize_failed)
        self.vm.timezone_changed.connect(self._on_timezone_changed)
        self.vm.filter_vm.time_range_changed.connect(self._refresh_measurement_context)
        self.vm.time_config_vm.timezone_changed.connect(self._refresh_measurement_context)
        self.vm.measurement_status_vm.status_changed.connect(self._refresh_measurement_status)
        self.vm.bus_statistics_vm.statistics_changed.connect(self._refresh_bus_statistics_summary)
        self.vm.measurement_status_vm.memory_warning_requested.connect(self._offer_memory_cleanup)
        self.vm.log_cleared.connect(self._on_log_cleared)

        self._recording_path: str | None = None
        self._recording_size = 0
        self._recording_status = QLabel(self)
        self._recording_status.setVisible(False)
        self.statusBar().addPermanentWidget(self._recording_status)
        self._measurement_labels = [QLabel(self) for _ in range(7)]
        self._measurement_labels[0].setObjectName("measurementConnection")
        for label in self._measurement_labels:
            label.setMargin(4)
            self.statusBar().addPermanentWidget(label)
        self._refresh_measurement_status(self.vm.measurement_status_vm.status)
        self.vm.continuous_recorder_vm.recording_started.connect(self._on_recording_started)
        self.vm.continuous_recorder_vm.size_changed.connect(self._on_recording_size_changed)
        self.vm.continuous_recorder_vm.recording_stopped.connect(self._on_recording_stopped)
        self.vm.continuous_recorder_vm.recording_failed.connect(self._on_recording_failed)

        self.statusBar().showMessage(get_text("status_ready", "Ready"))
        self.vm.dbc_restore_started.connect(self._show_dbc_restore_progress)
        self.vm.dbc_restore_progress.connect(self._on_dbc_restore_progress)
        self.vm.dbc_restore_finished.connect(self._on_dbc_restore_finished)
        self.vm.dbc_restore_failed.connect(self._on_dbc_restore_failed)

        _current_theme = self.vm.session_state.get_theme() or get_option("theme", DEFAULT_THEME)

        # Keep the hidden menu bar so its QActions (Ctrl+O, Ctrl+S …) still fire.
        build_main_menu(
            self,
            on_load=self._pick_load_log,
            on_append=self._pick_append_log,
            on_save=self._save_current_log_menu,
            on_clear=self._clear_log,
            on_open_dbc=self._open_dbc_manager,
            on_open_working_dbc=self._open_working_dbc,
            on_open_plot=lambda: self.plot_manager.open_plot_window(),
            on_analyze_data=self.analyze_data_manager.open_window,
            on_candidate_interpretations=self.candidate_interpretations_manager.open_window,
            on_signal_coverage=self.signal_coverage_manager.open_window,
            on_range_diff=self.range_diff_manager.open_window,
            on_can_send=self.can_send_manager.open_window,
            on_time_config=self._open_time_config,
            on_time_filter=self._open_time_filter,
            on_connection=self._open_connection,
            on_set_theme=self._set_theme,
            on_open_debug_log=self.debug_log_manager.open_window,
            on_open_plugins=self._open_plugins,
            current_theme=_current_theme,
        )
        self.menuBar().setVisible(False)

        self._ribbon = RibbonBar(
            RibbonCallbacks(
                on_load=self._pick_load_log,
                on_append=self._pick_append_log,
                on_save=self._save_current_log_menu,
                on_clear=self._clear_log,
                on_open_dbc=self._open_dbc_manager,
                on_open_working_dbc=self._open_working_dbc,
                on_open_plot=lambda: self.plot_manager.open_plot_window(),
                on_analyze_data=self.analyze_data_manager.open_window,
                on_candidate_interpretations=self.candidate_interpretations_manager.open_window,
                on_signal_coverage=self.signal_coverage_manager.open_window,
                on_bus_statistics=self.bus_statistics_manager.open_window,
                on_range_diff=self.range_diff_manager.open_window,
                on_can_send=self.can_send_manager.open_window,
                on_real_time_analysis=self.real_time_analysis_manager.open_window,
                on_time_config=self._open_time_config,
                on_time_filter=self._open_time_filter,
                on_connection=self._open_connection,
                on_toggle_connection=self._toggle_last_connection,
                on_start_connection=self._start_last_connection,
                on_stop_connection=self._stop_last_connection,
                on_set_theme=self._set_theme,
                on_about=self._open_about,
                on_open_debug_log=self.debug_log_manager.open_window,
                on_open_plugins=self._open_plugins,
                current_theme=_current_theme,
            ),
            parent=self,
        )
        self.setMenuWidget(self._ribbon)
        self.vm.plugin_vm.plugins_changed.connect(self._refresh_plugin_ui)
        self._refresh_plugin_ui(self.vm.plugin_vm.refresh())
        self.vm.connection_vm.running_changed.connect(self._ribbon.set_real_time_analysis_enabled)
        self.vm.connection_vm.running_changed.connect(self._ribbon.set_connection_running)
        self.vm.connection_vm.running_changed.connect(self._refresh_connection_availability)
        self._ribbon.set_connection_running(self.vm.connection_vm.running)
        self._ribbon.set_connection_available(
            bool(self._connection_dialog and self._connection_dialog.has_last_connection)
        )

        self._recent_logs_menu = self._ribbon.get_recent_logs_menu()
        self._refresh_recent_menus()
        self.vm.start_restore_dbcs()
        QTimer.singleShot(0, self._offer_interrupted_recording)

    def _on_recording_started(self, path: str) -> None:
        self._recording_path = path
        self._recording_size = 0
        self._refresh_recording_status()

    @staticmethod
    def _format_memory(size: int | None) -> str:
        if size is None:
            return get_text("measurement_unknown_memory")
        return f"{size / (1024 ** 2):,.0f} MB"

    def _refresh_measurement_status(self, status, *_args) -> None:
        labels = self._measurement_labels
        connection = self.vm.connection_vm
        connected = connection.running
        source = connection.capture_source_label if connected else ""
        labels[0].setText(get_text(
            "measurement_connection_active" if connected else "measurement_connection_idle"
        ).format(source=source.split("_")[0] if source else ""))
        labels[0].setStyleSheet(
            f"color: {get_active_theme().success};" if connected else ""
        )
        labels[0].setToolTip(connection.capture_source_label if connected else get_text("measurement_offline_tooltip"))
        memory = status.process_memory_bytes
        self._refresh_bus_statistics_summary(self.vm.bus_statistics_vm.snapshot)
        labels[2].setText(get_text("measurement_frames").format(count=status.frame_count))
        labels[3].setText(get_text("measurement_memory").format(memory=self._format_memory(memory)))
        names = status.active_dbc_names
        dbc_name = names[0][:12] + ("…" if len(names[0]) > 12 else "") if names else get_text("measurement_no_dbc")
        if len(names) > 1:
            dbc_name = f"{dbc_name}+{len(names) - 1}"
        labels[4].setText(get_text("measurement_dbc").format(name=dbc_name))
        labels[4].setToolTip(", ".join(names) or get_text("dbc_empty"))
        start, end = self.vm.filter_vm.time_range
        if start is None and end is None:
            labels[5].setText(get_text("measurement_time_filter_off"))
            labels[5].setToolTip(get_text("measurement_time_filter_off"))
        else:
            labels[5].setText(get_text("measurement_time_filter_on"))
            labels[5].setToolTip(
                f"{start if start is not None else get_text('measurement_time_bound_missing')} – "
                f"{end if end is not None else get_text('measurement_time_bound_missing')}"
            )
        labels[6].setText(get_text("measurement_timezone").format(
            timezone=self.vm.time_config_vm.timezone or get_text("measurement_empty_timezone")
        ))
        labels[6].setToolTip(self.vm.time_config_vm.timezone or get_text("measurement_empty_timezone"))

    def _refresh_measurement_context(self, *_args) -> None:
        self._refresh_measurement_status(self.vm.measurement_status_vm.status)

    def _refresh_bus_statistics_summary(
        self, snapshot: BusStatisticsSnapshot, live_fps: float | None = None
    ) -> None:
        load = (
            get_text("bus_statistics_unavailable")
            if snapshot.estimated_load_percent is None
            else get_text("bus_statistics_load_percent").format(value=snapshot.estimated_load_percent)
        )
        if live_fps is None and self.vm.connection_vm.running:
            live_fps = self.vm.measurement_status_vm.status.frames_per_second
        fps = snapshot.frames_per_second if live_fps is None else live_fps
        labels = self._measurement_labels
        labels[1].setText(get_text("bus_statistics_status").format(
            fps=fps, load=load, ids=snapshot.can_id_count,
        ))
        labels[1].setToolTip(get_text("bus_statistics_status_tooltip").format(
            bitrate=(
                get_text("bus_statistics_bitrate").format(value=snapshot.bitrate)
                if snapshot.bitrate else get_text("bus_statistics_unknown")
            ),
            new=", ".join(snapshot.new_ids) or get_text("bus_statistics_unavailable"),
            missing=", ".join(snapshot.missing_ids) or get_text("bus_statistics_unavailable"),
        ))

    def _offer_memory_cleanup(self, memory: int, threshold: int) -> None:
        recorder_path = self.vm.continuous_recorder_vm.active_path
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(get_text("measurement_memory_warning_title"))
        box.setText(get_text("measurement_memory_warning").format(
            memory=self._format_memory(memory),
            threshold=self._format_memory(threshold),
            recording=(get_text("measurement_recording_active").format(path=recorder_path)
                       if recorder_path else get_text("measurement_recording_inactive")),
            capture_action=(get_text("measurement_capture_will_stop")
                            if self.vm.connection_vm.running else ""),
        ))
        save_button = box.addButton(get_text("measurement_save_and_clear"), QMessageBox.AcceptRole)
        box.addButton(get_text("measurement_later"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() != save_button:
            return
        try:
            saved_path = self._save_current_log(stop_capture=True)
        except Exception as exc:
            QMessageBox.critical(
                self, get_text("measurement_memory_warning_title"),
                get_text("measurement_clear_save_failed").format(error=str(exc)),
            )
            return
        if saved_path:
            self.vm.clear_log()

    def _on_recording_size_changed(self, size: int) -> None:
        self._recording_size = size
        self._refresh_recording_status()

    def _refresh_recording_status(self) -> None:
        if not self._recording_path:
            self._recording_status.setVisible(False)
            return
        self._recording_status.setText(get_text("continuous_recording_status").format(
            name=Path(self._recording_path).name,
            size=self._recording_size / (1024 * 1024),
        ))
        self._recording_status.setVisible(True)

    def _on_recording_stopped(self, path: str) -> None:
        if path == self._recording_path:
            self._recording_path = None
            self._refresh_recording_status()

    def _on_recording_failed(self, message: str) -> None:
        self._recording_path = None
        self._recording_status.setText(get_text("continuous_recording_failed").format(error=message))
        self._recording_status.setVisible(True)

    def _offer_interrupted_recording(self) -> None:
        interrupted = self.vm.interrupted_recording
        if interrupted is None:
            return
        path, _marker = interrupted
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(get_text("continuous_recording_recovery_title"))
        box.setText(get_text("continuous_recording_recovery_message").format(name=path.name))
        box.setDetailedText(str(path))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        answer = box.exec()
        self.vm.dismiss_interrupted_recording()
        if answer == QMessageBox.Yes:
            self._start_log_load(path=str(path), mode="load")

    def _unsaved_capture_prompt_text(self, action: str) -> str:
        path = self.vm.continuous_recorder_vm.active_path
        key = "unsaved_capture_recording_message" if path else "unsaved_capture_message"
        values = {"frames": self.vm.data_vm.unsaved_capture_frame_count, "action": action}
        if path:
            values["path"] = path
        return get_text(key).format(**values)

    def _refresh_recent_menus(self) -> None:
        self._populate_recent_menu(
            self._recent_logs_menu,
            self.vm.session_state.get_recent_logs(),
            lambda path: self._start_log_load(path=path, mode="load"),
        )

    def _populate_recent_menu(self, menu: QMenu | None, items: list[str], callback) -> None:
        if menu is None:
            return
        menu.clear()
        if not items:
            empty = menu.addAction("(empty)")
            empty.setEnabled(False)
            return
        for path in items:
            action = menu.addAction(path)
            action.triggered.connect(lambda checked=False, p=path: callback(p))

    def _open_time_config(self) -> None:
        dlg = TimeConfigDialog(
            self.vm.time_config_vm, parent=self, before_apply=self._confirm_normalize_change
        )
        dlg.exec()

    def _open_time_filter(self) -> None:
        dlg = TimeFilterDialog(self.vm.time_config_vm, state=self.vm.time_range_vm.filter_state, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        ts_min, ts_max = dlg.get_range()
        if ts_min is not None and ts_max is not None and ts_min > ts_max:
            QMessageBox.warning(self, get_text("time_filter_title"), get_text("time_filter_invalid_range"))
            return
        self.vm.time_range_vm.set_time_range(ts_min, ts_max, filter_state=dlg.get_state())

    def _set_theme(self, name: str) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, name)
        self.vm.session_state.set_theme(name)
        clear_icon_cache()
        self._ribbon.reload_icons()
        self._ribbon.update_theme_check(name)

    def _show_dbc_restore_progress(self) -> None:
        self._dbc_restore_progress = EtaProgressDialog(
            get_text("status_dbc_restoring", "Restoring DBCs…"), get_text("cancel"), self
        )
        self._dbc_restore_progress.canceled.connect(self.vm.cancel_restore_dbcs)
        self._dbc_restore_progress.start()

    def _on_dbc_restore_progress(self, done: int, total: int) -> None:
        if self._dbc_restore_progress is not None:
            self._dbc_restore_progress.report_progress(done, total)

    def _close_dbc_restore_progress(self) -> None:
        if self._dbc_restore_progress is not None:
            self._dbc_restore_progress.close()
            self._dbc_restore_progress = None

    def _on_dbc_restore_finished(self, restored: bool) -> None:
        self._close_dbc_restore_progress()
        self.vm.plugin_vm.refresh()
        if restored:
            self.statusBar().showMessage(get_text("status_dbc_restored", "DBCs restored"), 4000)
        else:
            self.statusBar().clearMessage()

    def _on_dbc_restore_failed(self, message: str) -> None:
        self._close_dbc_restore_progress()
        self.vm.plugin_vm.refresh()
        self.statusBar().showMessage(
            get_text("status_dbc_restore_failed", "DBC restore failed: {error}").format(error=message),
            8000,
        )

    def _open_about(self) -> None:
        AboutDialog(self).exec()

    def _open_plugins(self) -> None:
        PluginsDialog(self.vm.plugin_vm, parent=self).exec()

    def _refresh_plugin_ui(self, _records: tuple[PluginRecord, ...] = ()) -> None:
        windows = self.vm.plugin_vm.ui_extensions("windows")
        plugin_names = {record.id: record.name for record in _records}
        for extension_id, window in tuple(self._plugin_windows.items()):
            if extension_id not in windows:
                window.close()
        ribbon_items = []
        for extension_id, (owner, _factory) in windows.items():
            label = extension_id.split(":", 1)[1].replace("_", " ").strip().title()
            label = f"{plugin_names.get(owner, owner)}: {label}"
            ribbon_items.append((label, lambda key=extension_id: self._open_plugin_window(key)))
        self._ribbon.set_plugin_windows(ribbon_items)

    def _open_plugin_window(self, extension_id: str) -> None:
        existing = self._plugin_windows.get(extension_id)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        extension = self.vm.plugin_vm.ui_extensions("windows").get(extension_id)
        if extension is None:
            return
        owner, factory = extension
        try:
            window = factory(self.vm.plugin_vm.context_for_plugin(owner))
            if not isinstance(window, QWidget):
                raise TypeError("Plugin window factories must return a QWidget")
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            enable_window_geometry_persistence(
                window, self.vm.session_state, f"PluginWindow:{owner}:{extension_id}"
            )
            self._plugin_windows[extension_id] = window
            window.destroyed.connect(
                lambda _obj=None, key=extension_id: self._plugin_windows.pop(key, None)
            )
            window.show()
        except Exception as exc:
            self.statusBar().showMessage(f"Plugin window failed: {exc}", 8000)

    def _open_connection(self) -> None:
        if self._connection_dialog is None:
            self._connection_dialog = ConnectionDialog(
                self.vm.connection_vm,
                replay_offset_getter=self._current_replay_offset,
                normalize_getter=lambda: bool(getattr(self.vm.data_vm, "normalize", False)),
                time_config_vm=self.vm.time_config_vm,
                confirm_new_session=self._confirm_new_session,
                before_normalize_apply=self._confirm_normalize_change,
                parent=self,
            )
        self._connection_dialog.show()
        self._connection_dialog.raise_()
        self._connection_dialog.activateWindow()

    def _refresh_connection_availability(self, _running: bool) -> None:
        available = bool(self._connection_dialog and self._connection_dialog.has_last_connection)
        self._ribbon.set_connection_available(available)

    def _show_frame_context_menu(
        self, table_model: object, row: int, global_pos: object
    ) -> None:
        record = table_model.get_row_record(row)
        if record is None:
            return
        show_frame_context_menu(
            self,
            global_pos,
            record,
            plot_manager=self.plot_manager,
            candidate_manager=self.candidate_interpretations_manager,
            analysis_context_vm=self.vm.analysis_context_vm,
        )

    def _start_last_connection(self) -> None:
        if self.vm.connection_vm.running:
            return
        if self._connection_dialog is None or not self._connection_dialog.has_last_connection:
            self._open_connection()
            return
        self._connection_dialog.start_last_connection()

    def _stop_last_connection(self) -> None:
        if self._connection_dialog is None:
            self.vm.connection_vm.stop()
            return
        self._connection_dialog.stop_connection()

    def _toggle_last_connection(self) -> None:
        if self.vm.connection_vm.running:
            self._stop_last_connection()
        else:
            self._start_last_connection()

    def _pick_load_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, get_text("load_log_title"), "", get_text("log_files_filter")
        )
        if path:
            self._start_log_load(path=path, mode="load")

    def _pick_append_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, get_text("append_log_title"), "", get_text("log_files_filter")
        )
        if path:
            self._start_log_load(path=path, mode="append")

    @staticmethod
    def _dropped_log_path(mime_data: QMimeData) -> str | None:
        if not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(
                (".log", ".txt", ".asc", ".blf", ".trc", ".csv")
            ):
                return url.toLocalFile()
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_log_path(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        path = self._dropped_log_path(event.mimeData())
        if path is None:
            return
        event.acceptProposedAction()
        self._start_log_load(path=path, mode="load")

    def _start_log_load(self, *, path: str, mode: str) -> None:
        tz_selection = self._prompt_log_utc_offset(path, mode)
        if tz_selection is False:
            return
        if mode == "load" and not self._confirm_data_change(DataChangeAction.LOAD):
            return
        source_tz_offset_minutes, selected_timezone = tz_selection
        if selected_timezone:
            self.vm.time_config_vm.apply(
                normalize=bool(getattr(self.vm.data_vm, "normalize", False)),
                timezone=selected_timezone,
            )
        self.vm.start_load(
            path=path,
            mode=mode,
            source_tz_offset_minutes=source_tz_offset_minutes if isinstance(source_tz_offset_minutes, int) else None,
        )
        self._refresh_recent_menus()

    def _prompt_log_utc_offset(self, path: str, mode: str) -> tuple[int | None, str | None] | bool:
        if mode == "load" and bool(getattr(self.vm.data_vm, "normalize", False)):
            return (None, None)

        created_at_text = self.vm.data_vm.kvaser_timestamp_prompt_text(path)
        if not created_at_text:
            return (None, None)

        dlg = LogTimezoneDialog(created_at_text=created_at_text, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        return (dlg.offset_minutes, dlg.timezone_name)

    def _show_load_progress(self, _path: str) -> None:
        self._load_progress = QProgressDialog(get_text("loading_log"), get_text("cancel"), 0, 0, self)
        self._load_progress.setWindowTitle(get_text("loading_title"))
        self._load_progress.setWindowModality(Qt.WindowModal)
        self._load_progress.canceled.connect(self.vm.log_load_vm.cancel)
        self._load_progress.show()

    def _set_load_failed_text(self, message: str) -> None:
        if self._load_progress:
            self._load_progress.setLabelText(get_text("failed_prefix").format(error=message))

    def _hide_load_progress(self) -> None:
        if self._load_progress:
            self._load_progress.close()
            self._load_progress = None

    def _open_dbc_manager(self) -> None:
        dlg = DbcManagerDialog(
            self.vm.dbc_manager,
            on_loaded=self._on_dbc_loaded,
            parent=self,
        )
        dlg.exec()

    def _open_working_dbc(self) -> None:
        if self._working_dbc_dialog is not None:
            self._working_dbc_dialog.raise_()
            self._working_dbc_dialog.activateWindow()
            return
        dialog = WorkingDbcDialog(self.vm, self)
        self._working_dbc_dialog = dialog
        dialog.destroyed.connect(lambda *_: setattr(self, "_working_dbc_dialog", None))
        dialog.show()

    def _clear_log(self) -> None:
        if not self._confirm_data_change(DataChangeAction.CLEAR):
            return
        self.vm.clear_log()

    def _confirm_data_change(self, action: DataChangeAction) -> bool:
        df = self.vm.data_vm.df
        has_data = df is not None and not df.is_empty()
        kind = unsaved_prompt_kind(has_data, self.vm.data_vm.has_unsaved_capture)
        if kind == "none" or (kind == "confirm" and action is not DataChangeAction.CLEAR):
            return True
        if kind == "confirm" and action is DataChangeAction.CLEAR:
            reply = QMessageBox.question(
                self,
                get_text("clear_log_confirm_title"),
                get_text("clear_log_confirm_message"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return reply == QMessageBox.Yes

        box = QMessageBox(self)
        box.setWindowTitle(get_text("unsaved_capture_title"))
        action_text = get_text({
            DataChangeAction.CLEAR: "unsaved_action_clear",
            DataChangeAction.LOAD: "unsaved_action_load",
            DataChangeAction.CLOSE: "unsaved_action_close",
        }[action])
        box.setText(self._unsaved_capture_prompt_text(action_text))
        save_button = box.addButton(get_text("unsaved_capture_save"), QMessageBox.AcceptRole)
        discard_button = box.addButton(get_text("unsaved_capture_discard"), QMessageBox.DestructiveRole)
        box.addButton(get_text("unsaved_capture_cancel"), QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == discard_button:
            return True
        if clicked != save_button:
            return False
        try:
            saved_path = self._save_current_log(stop_capture=True)
        except Exception as exc:
            QMessageBox.critical(
                self,
                get_text("menu_save_log"),
                get_text("save_log_error_prefix").format(error=str(exc)),
            )
            return False
        if not saved_path:
            return False
        return True

    def _confirm_new_session(self) -> str:
        prompt_kind = new_session_prompt_kind(self.vm.data_vm.has_unsaved_capture)
        if prompt_kind == "none":
            return "append"
        box = QMessageBox(self)
        box.setWindowTitle(get_text("unsaved_capture_title"))
        box.setText(self._unsaved_capture_prompt_text(get_text("unsaved_action_connection")))
        save_button = box.addButton(get_text("unsaved_capture_save"), QMessageBox.AcceptRole)
        discard_button = box.addButton(get_text("unsaved_capture_discard"), QMessageBox.DestructiveRole)
        append_button = box.addButton(get_text("new_session_append"), QMessageBox.ActionRole)
        box.addButton(get_text("unsaved_capture_cancel"), QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == append_button:
            return "append"
        if clicked == discard_button:
            self.vm.clear_log()
            return "discard"
        if clicked != save_button:
            return "cancel"
        try:
            if not self._save_current_log(stop_capture=True):
                return "cancel"
        except Exception as exc:
            QMessageBox.critical(self, get_text("menu_save_log"),
                                 get_text("save_log_error_prefix").format(error=str(exc)))
            return "cancel"
        return "append"

    def _confirm_normalize_change(self, normalize: bool) -> bool:
        data_vm = self.vm.data_vm
        if (normalize == data_vm.normalize or not data_vm.has_unsaved_capture
                or not data_vm.has_reloadable_log):
            return True
        box = QMessageBox(self)
        box.setWindowTitle(get_text("normalize_discard_title"))
        box.setText(get_text("normalize_discard_message"))
        save_button = box.addButton(get_text("unsaved_capture_save"), QMessageBox.AcceptRole)
        discard_button = box.addButton(get_text("unsaved_capture_discard"), QMessageBox.DestructiveRole)
        box.addButton(get_text("unsaved_capture_cancel"), QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == discard_button:
            return True
        if clicked != save_button:
            return False
        try:
            return bool(self._save_current_log(stop_capture=True))
        except Exception as exc:
            QMessageBox.critical(self, get_text("menu_save_log"),
                                 get_text("save_log_error_prefix").format(error=str(exc)))
            return False

    def _save_current_log_menu(self) -> None:
        try:
            saved_path = self._export_current_log()
        except ValueError:
            QMessageBox.information(self, get_text("menu_save_log"), get_text("connection_no_data_to_save"))
        except Exception as exc:
            QMessageBox.critical(
                self,
                get_text("menu_save_log"),
                get_text("save_log_error_prefix").format(error=str(exc)),
            )
        else:
            if saved_path:
                QMessageBox.information(
                    self,
                    get_text("menu_save_log"),
                    get_text("log_export_succeeded_prefix").format(path=saved_path),
                )

    def _save_current_log(self, *, stop_capture: bool = False) -> str:
        path = self._choose_log_export_path()
        if not path:
            return ""
        return self._export_snapshot(path, "all", None, None, stop_capture=stop_capture)

    def _export_current_log(self) -> str:
        dialog = LogExportDialog(
            self.vm.time_config_vm,
            filter_state=self.vm.time_range_vm.filter_state,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return ""
        scope, ts_min, ts_max = dialog.selection()
        path = self._choose_log_export_path()
        if not path:
            return ""
        return self._export_snapshot(path, scope, ts_min, ts_max)

    def _choose_log_export_path(self) -> str:
        filters = ";;".join(get_text(key) for key in (
            "log_export_filter_candump",
            "log_export_filter_asc",
            "log_export_filter_blf",
            "log_export_filter_trc",
            "log_export_filter_csv",
        ))
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            get_text("log_export_title"),
            "",
            filters,
        )
        if not path:
            return ""
        if not Path(path).suffix:
            suffix = selected_filter.partition("*.")[2].partition(")")[0]
            if suffix:
                path = f"{path}.{suffix}"
        return path

    def _export_snapshot(
        self,
        path: str,
        scope: str,
        ts_min: float | None,
        ts_max: float | None,
        *,
        stop_capture: bool = False,
    ) -> str:
        data_vm = self.vm.data_vm
        if stop_capture:
            self.vm.connection_vm.stop_and_drain()
        data_vm.flush_pending()
        source = data_vm.df
        if source is None or source.is_empty():
            raise ValueError(get_text("connection_no_data_to_save"))
        revision = data_vm.data_revision
        selected = self.vm.log_export_vm.select_frames(
            source,
            scope,
            selected_ids=self.vm.filter_vm.selected_ids,
            ts_min=ts_min if scope == "range" else self.vm.filter_vm.time_range[0],
            ts_max=ts_max if scope == "range" else self.vm.filter_vm.time_range[1],
        )
        if selected.is_empty():
            raise ValueError(get_text("log_export_no_matching_frames"))

        export_vm = self.vm.log_export_vm
        protected_paths = list(data_vm.source_paths)
        protected_paths.extend(self.vm.continuous_recorder_vm.recorded_paths)
        if not export_vm.start_export(selected, path, protected_paths=protected_paths):
            raise RuntimeError(get_text("log_export_already_running"))
        progress = EtaProgressDialog(get_text("log_export_progress"), get_text("cancel"), self)
        progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        export_vm.progress_changed.connect(progress.report_progress)
        progress.canceled.connect(export_vm.cancel)
        progress.start()
        try:
            while export_vm.running:
                export_vm.wait(50)
                QApplication.processEvents()
            QApplication.processEvents()
        finally:
            export_vm.progress_changed.disconnect(progress.report_progress)
            progress.close()

        if export_vm.error_message:
            raise RuntimeError(export_vm.error_message)
        if export_vm.was_canceled or not export_vm.result_path:
            return ""
        if scope == "all" and selected.height == source.height:
            data_vm.mark_capture_saved(expected_revision=revision)
        return export_vm.result_path

    def _on_interpret_enabled_changed(self, enabled: bool) -> None:
        self.view.panel.set_interpret_checked(enabled)
        self.view.panel.refresh_labels()
        self.row_heights.refresh()

    def _jump_to_can_id(self) -> None:
        can_ids = list(self.vm.data_vm.can_ids)
        if not can_ids:
            return
        dialog = CanIdJumpDialog(can_ids, self)
        accepted = dialog.exec() == QDialog.Accepted
        target = dialog.selected_can_id if accepted else None
        dialog.deleteLater()
        if not target:
            return

        self.view.panel.search_box.clear()
        self.view.panel.set_checked_ids(self.view.panel.selected_ids() | {target})
        QTimer.singleShot(0, lambda: self._complete_can_id_jump(target))

    def _complete_can_id_jump(self, can_id: str, *, time_filter_checked: bool = False, retries: int = 0) -> None:
        table_model = self.view.table.model()
        if "ID" not in table_model._columns:
            return
        id_column = table_model._columns.index("ID")
        row = self._first_visible_row_for_can_id(can_id)
        if row < 0 and not time_filter_checked:
            if self.vm.time_range_vm.time_range != (None, None):
                self.vm.time_range_vm.set_time_range(None, None)
                self.statusBar().showMessage(get_text("can_id_jump_cleared_time_filter"), 5000)
            QTimer.singleShot(0, lambda: self._complete_can_id_jump(can_id, time_filter_checked=True))
            return
        if row < 0 and retries < 10:
            QTimer.singleShot(
                0,
                lambda: self._complete_can_id_jump(
                    can_id,
                    time_filter_checked=True,
                    retries=retries + 1,
                ),
            )
            return
        if row >= 0:
            index = table_model.index(row, id_column)
            self.view.table.selectRow(row)
            self.view.table.scrollTo(index, QAbstractItemView.PositionAtCenter)

    def _first_visible_row_for_can_id(self, can_id: str) -> int:
        table_model = self.view.table.model()
        first_row = -1
        first_timestamp: float | None = None
        for row in range(table_model.rowCount()):
            record = table_model.get_row_record(row)
            if str(record.get("ID", "")).upper() != can_id.upper():
                continue
            timestamp = float(record.get("TS", 0.0))
            if first_timestamp is None or timestamp < first_timestamp:
                first_row = row
                first_timestamp = timestamp
        return first_row

    def _on_expand_all(self) -> None:
        if self.vm.interpret_vm.enabled:
            self.row_heights.expand_all()

    def _on_collapse_all(self) -> None:
        if self.vm.interpret_vm.enabled:
            self.row_heights.collapse_all()

    def _on_normalize_applied(self, _normalize: bool) -> None:
        self.view.table.viewport().update()

    def _on_normalize_failed(self, message: str) -> None:
        self.statusBar().showMessage(
            get_text("status_normalize_failed", "Normalization failed: {error}").format(error=message),
            8000,
        )

    def _on_timezone_changed(self, tz: str) -> None:
        self._timezone_mode = tz
        self._ts_delegate.set_timezone_mode(tz)
        self._resize_timestamp_column()
        self.view.table.viewport().update()

    def _resize_timestamp_column(self) -> None:
        column = DEFAULT_COLUMNS.index("TS")
        sample_timestamp = 1_700_000_000.0
        dataframe = self.vm.data_vm.df
        if dataframe is not None and not dataframe.is_empty() and "TS" in dataframe.columns:
            try:
                sample_timestamp = max(
                    (float(dataframe[0, "TS"]), float(dataframe[-1, "TS"])),
                    key=abs,
                )
            except (TypeError, ValueError):
                pass
        sample = self._ts_delegate.displayText(sample_timestamp, self.view.table.locale())
        width = self.view.table.fontMetrics().horizontalAdvance(sample)
        section_width = self.view.table.horizontalHeader().sectionSizeHint(column)
        self.view.table.setColumnWidth(column, max(width + 16, section_width))

    def _on_log_cleared(self) -> None:
        self.row_heights.refresh()
        self.view.table.viewport().update()

    def _current_replay_offset(self) -> float:
        df = getattr(self.vm.data_vm, "df", None)
        if df is None or df.is_empty() or "TS" not in df.columns:
            return 0.0
        try:
            return float(df[-1, "TS"])
        except Exception:
            return 0.0

    def _on_dbc_loaded(self, path: str) -> None:
        self.vm.session_state.add_recent_dbc(path)

    def _has_open_secondary_windows(self) -> bool:
        if any(window.isVisible() for window in self._plugin_windows.values()):
            return True
        if self.plot_manager._plot_windows:
            return True
        for mgr in (
            self.real_time_analysis_manager,
            self.analyze_data_manager,
            self.candidate_interpretations_manager,
            self.signal_coverage_manager,
            self.bus_statistics_manager,
            self.range_diff_manager,
            self.can_send_manager,
            self.debug_log_manager,
        ):
            if getattr(mgr, "_window", None) is not None:
                return True
        return False

    def _close_all_secondary_windows(self) -> None:
        self.plot_manager.close_all()
        for window in tuple(self._plugin_windows.values()):
            window.close()
        for mgr in (
            self.real_time_analysis_manager,
            self.analyze_data_manager,
            self.candidate_interpretations_manager,
            self.signal_coverage_manager,
            self.bus_statistics_manager,
            self.range_diff_manager,
            self.can_send_manager,
            self.debug_log_manager,
        ):
            win = getattr(mgr, "_window", None)
            if win is not None:
                win.close()

    def _route_analysis_context(self, destination: str, context: AnalysisContext) -> None:
        source = context.source_window or get_text("analysis_context_source_unknown")
        if destination == "working_dbc":
            self._open_save_signal_dialog(context)
        elif destination == "candidate" and context.can_id:
            self.candidate_interpretations_manager.open_window_for_context(context)
        elif destination == "diff":
            self.range_diff_manager.open_window()
            if context.range_a is not None:
                self.vm.range_diff_vm.set_range_a(*context.range_a)
            if context.range_b is not None:
                self.vm.range_diff_vm.set_range_b(*context.range_b)
        elif destination == "analyze":
            self.analyze_data_manager.open_window()
            if context.can_id:
                self.vm.analyze_data_vm.set_selected_id(context.can_id)
            if context.time_range is not None:
                self.vm.time_range_vm.set_time_range(*context.time_range)
        elif destination == "realtime" and context.can_id:
            self.real_time_analysis_manager.open_window_for_can_id(context.can_id, source=source)

    def _open_save_signal_dialog(self, context: AnalysisContext) -> None:
        if not context.can_id:
            return
        defaults = self.vm.working_signal_dialog_defaults(context.can_id)
        dialog = SaveSignalDialog(context, defaults, parent=self)
        dialog.save_requested.connect(lambda params: self._save_working_signal(dialog, params))
        self._save_signal_dialog = dialog
        dialog.exec()
        self._save_signal_dialog = None

    def _save_working_signal(self, dialog: SaveSignalDialog, params: dict[str, object]) -> None:
        try:
            result = self.vm.save_working_signal(params)
        except Exception as exc:
            dialog.show_error(str(exc))
            return
        self.statusBar().showMessage(
            get_text("save_signal_saved").format(
                signal=result["signal_name"], path=result["path"],
            ),
            6000,
        )
        dialog.accept()

    def closeEvent(self, event) -> None:
        if not self._confirm_data_change(DataChangeAction.CLOSE):
            event.ignore()
            return
        if self._has_open_secondary_windows():
            reply = QMessageBox.question(
                self,
                "Close Canlytics",
                "There are open windows. Close all and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        self.setEnabled(False)
        self.setCursor(Qt.WaitCursor)
        QApplication.processEvents()
        self._close_all_secondary_windows()
        self.vm.shutdown()
        self.unsetCursor()
        super().closeEvent(event)
