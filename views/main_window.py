from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QFileDialog, QProgressDialog

from config.defaults import DEFAULT_COLUMNS
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.dbc.dbc_manager_dialog import DbcManagerDialog
from views.main_window_view import MainWindowView
from views.menu.main_menu_factory import build_main_menu
from views.analyze_data_window_manager import AnalyzeDataWindowManager
from views.plot.plot_window_manager import PlotWindowManager
from views.realtime_analysis_window_manager import RealTimeAnalysisWindowManager
from views.settings.connection_dialog import ConnectionDialog
from views.table.row_height_manager import RowHeightManager
from views.table.ts_display_delegate import TsDisplayDelegate
from views.settings.time_config_dialog import TimeConfigDialog
from config.app_config import get_text


class MainWindow(QMainWindow):
    def __init__(self, viewmodel: MainWindowViewModel):
        super().__init__()
        self.setWindowTitle(get_text("main_window_title"))
        self.resize(1200, 700)

        self.vm = viewmodel
        self._timezone_mode = self.vm.timezone_mode
        self._load_progress: QProgressDialog | None = None
        self._connection_dialog: ConnectionDialog | None = None

        self.view = MainWindowView(
            self.vm.table_model,
            dbc_manager=self.vm.dbc_manager,
            interpret_vm=self.vm.interpret_vm,
            parent=self,
        )
        self.setCentralWidget(self.view)

        self._ts_delegate = TsDisplayDelegate(self._timezone_mode, parent=self.view.table)
        self.view.table.setItemDelegateForColumn(DEFAULT_COLUMNS.index("TS"), self._ts_delegate)

        self.row_heights = RowHeightManager(self.view.table, self.vm.table_model, self.vm.table_vm)
        self.plot_manager = PlotWindowManager(
            self,
            data_vm=self.vm.data_vm,
            dbc_manager=self.vm.dbc_manager,
            table_model=self.vm.table_model,
            get_timezone=lambda: self.vm.timezone_mode,
            interpret_enabled=lambda: self.vm.interpret_vm.enabled,
        )
        self.real_time_analysis_manager = RealTimeAnalysisWindowManager(
            analysis_vm=self.vm.real_time_analysis_vm,
            dbc_manager=self.vm.dbc_manager,
            parent=self,
        )
        self.analyze_data_manager = AnalyzeDataWindowManager(
            vm=self.vm.analyze_data_vm,
            parent=self,
        )

        self.view.panel.selected_ids_changed.connect(self.vm.filter_vm.set_selected_ids)
        self.view.panel.interpret_toggled.connect(self.vm.interpret_vm.set_enabled)

        self.view.panel.expand_all_clicked.connect(self._on_expand_all)
        self.view.panel.collapse_all_clicked.connect(self._on_collapse_all)

        self.vm.data_vm.can_ids_changed.connect(self.view.panel.set_can_ids)

        self.vm.interpret_vm.enabled_changed.connect(self._on_interpret_enabled_changed)
        self.vm.interpret_vm.available_changed.connect(lambda _: self.view.panel.refresh_labels())

        self.view.table.decode_context_requested.connect(self.plot_manager.on_decode_context)
        self.view.table.row_toggle_requested.connect(self.row_heights.toggle_row)

        self.vm.log_load_vm.load_started.connect(self._show_load_progress)
        self.vm.log_load_vm.load_finished.connect(self._hide_load_progress)
        self.vm.log_load_vm.load_failed.connect(self._set_load_failed_text)

        self.vm.normalize_applied.connect(self._on_normalize_applied)
        self.vm.timezone_changed.connect(self._on_timezone_changed)
        self.vm.log_cleared.connect(self._on_log_cleared)

        build_main_menu(
            self,
            on_load=self._pick_load_log,
            on_append=self._pick_append_log,
            on_clear=self._clear_log,
            on_open_dbc=self._open_dbc_manager,
            on_open_plot=lambda: self.plot_manager.open_plot_window(),
            on_analyze_data=self.analyze_data_manager.open_window,
            on_time_config=self._open_time_config,
            on_connection=self._open_connection,
        )

    def _open_time_config(self) -> None:
        dlg = TimeConfigDialog(self.vm.time_config_vm, parent=self)
        dlg.exec()

    def _open_connection(self) -> None:
        if self._connection_dialog is None:
            self._connection_dialog = ConnectionDialog(
                self.vm.connection_vm,
                open_real_time_analysis=self.real_time_analysis_manager.open_window,
                replay_offset_getter=self._current_replay_offset,
                normalize_getter=lambda: bool(getattr(self.vm.data_vm, "normalize", False)),
                parent=self,
            )
        self._connection_dialog.show()
        self._connection_dialog.raise_()
        self._connection_dialog.activateWindow()

    def _pick_load_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, get_text("load_log_title"), "", get_text("log_files_filter")
        )
        if path:
            self.vm.start_load(path=path, mode="load")

    def _pick_append_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, get_text("append_log_title"), "", get_text("log_files_filter")
        )
        if path:
            self.vm.start_load(path=path, mode="append")

    def _show_load_progress(self, _path: str) -> None:
        self._load_progress = QProgressDialog(get_text("loading_log"), get_text("cancel"), 0, 0, self)
        self._load_progress.setWindowTitle(get_text("loading_title"))
        self._load_progress.setWindowModality(Qt.ApplicationModal)
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
        dlg = DbcManagerDialog(self.vm.dbc_manager, parent=self)
        dlg.exec()

    def _clear_log(self) -> None:
        self.vm.clear_log()

    def _on_interpret_enabled_changed(self, enabled: bool) -> None:
        self.view.panel.set_interpret_checked(enabled)
        self.view.panel.refresh_labels()
        self.row_heights.refresh()

    def _on_expand_all(self) -> None:
        if self.vm.interpret_vm.enabled:
            self.row_heights.expand_all()

    def _on_collapse_all(self) -> None:
        if self.vm.interpret_vm.enabled:
            self.row_heights.collapse_all()

    def _on_normalize_applied(self, _normalize: bool) -> None:
        self.view.table.viewport().update()

    def _on_timezone_changed(self, tz: str) -> None:
        self._timezone_mode = tz
        self._ts_delegate.set_timezone_mode(tz)
        self.plot_manager.set_timezone(tz)
        self.view.table.viewport().update()

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

    def closeEvent(self, event) -> None:
        self.vm.shutdown()
        super().closeEvent(event)
