from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QFileDialog, QMenu, QMessageBox, QProgressDialog

from config.defaults import DEFAULT_COLUMNS
from services.can_data_parser import FORMAT_KVASER_MEMORATOR, inspect_log_metadata
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.candidate_interpretations_window_manager import CandidateInterpretationsWindowManager
from views.dbc.dbc_manager_dialog import DbcManagerDialog
from views.main_window_view import MainWindowView
from views.menu.main_menu_factory import build_main_menu
from views.analyze_data_window_manager import AnalyzeDataWindowManager
from views.hmi_video_extractor_window_manager import HmiVideoExtractorWindowManager
from views.mux_detection_window_manager import MuxDetectionWindowManager
from views.plot.plot_window_manager import PlotWindowManager
from views.realtime_analysis_window_manager import RealTimeAnalysisWindowManager
from views.settings.connection_dialog import ConnectionDialog
from views.settings.log_timezone_dialog import LogTimezoneDialog
from views.table.decode_line_layout_delegate import DecodeLineLayoutDelegate
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
        self._recent_logs_menu: QMenu | None = None

        self.view = MainWindowView(
            self.vm.table_model,
            dbc_manager=self.vm.dbc_manager,
            interpret_vm=self.vm.interpret_vm,
            time_config_vm=self.vm.time_config_vm,
            parent=self,
        )
        self.setCentralWidget(self.view)

        self._ts_delegate = TsDisplayDelegate(self._timezone_mode, parent=self.view.table)
        self.view.table.setItemDelegateForColumn(DEFAULT_COLUMNS.index("TS"), self._ts_delegate)
        self._decode_layout_delegate = DecodeLineLayoutDelegate(parent=self.view.table)
        self.view.table.setItemDelegateForColumn(DEFAULT_COLUMNS.index("DATA"), self._decode_layout_delegate)

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
            time_config_vm=self.vm.time_config_vm,
            parent=self,
        )
        self.analyze_data_manager = AnalyzeDataWindowManager(
            vm=self.vm.analyze_data_vm,
            time_config_vm=self.vm.time_config_vm,
            get_timezone=lambda: self.vm.timezone_mode,
            parent=self,
        )
        self.candidate_interpretations_manager = CandidateInterpretationsWindowManager(
            vm=self.vm.candidate_interpretations_vm,
            time_config_vm=self.vm.time_config_vm,
            session_state=self.vm.session_state,
            get_timezone=lambda: self.vm.timezone_mode,
            plot_manager=self.plot_manager,
        )
        self.mux_detection_manager = MuxDetectionWindowManager(
            vm=self.vm.mux_detection_vm,
            time_config_vm=self.vm.time_config_vm,
            get_timezone=lambda: self.vm.timezone_mode,
        )
        self.hmi_video_extractor_manager = HmiVideoExtractorWindowManager()

        self.view.panel.selected_ids_changed.connect(self.vm.filter_vm.set_selected_ids)
        self.view.panel.time_range_changed.connect(self.vm.filter_vm.set_time_range)
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

        menus = build_main_menu(
            self,
            on_load=self._pick_load_log,
            on_append=self._pick_append_log,
            on_save=self._save_current_log_menu,
            on_clear=self._clear_log,
            on_open_dbc=self._open_dbc_manager,
            on_open_plot=lambda: self.plot_manager.open_plot_window(),
            on_analyze_data=self.analyze_data_manager.open_window,
            on_candidate_interpretations=self.candidate_interpretations_manager.open_window,
            on_mux_detection=self.mux_detection_manager.open_window,
            on_hmi_video_extractor=self.hmi_video_extractor_manager.open_window,
            on_time_config=self._open_time_config,
            on_connection=self._open_connection,
        )
        self._setup_recent_menus(menus["file_menu"])
        self._refresh_recent_menus()
        self.vm.start_restore_dbcs()

    def _setup_recent_menus(self, file_menu: QMenu) -> None:
        self._recent_logs_menu = file_menu.addMenu("Recent Logs")

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
            self._start_log_load(path=path, mode="load")

    def _pick_append_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, get_text("append_log_title"), "", get_text("log_files_filter")
        )
        if path:
            self._start_log_load(path=path, mode="append")

    def _start_log_load(self, *, path: str, mode: str) -> None:
        tz_selection = self._prompt_log_utc_offset(path, mode)
        if tz_selection is False:
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

        metadata = inspect_log_metadata(path)
        if metadata.format != FORMAT_KVASER_MEMORATOR or not metadata.created_at_text:
            return (None, None)

        dlg = LogTimezoneDialog(created_at_text=metadata.created_at_text, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        return (dlg.offset_minutes, dlg.timezone_name)

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
        dlg = DbcManagerDialog(
            self.vm.dbc_manager,
            on_loaded=self._on_dbc_loaded,
            parent=self,
        )
        dlg.exec()

    def _clear_log(self) -> None:
        self.vm.clear_log()

    def _save_current_log_menu(self) -> None:
        try:
            saved_path = self._save_current_log()
        except ValueError:
            QMessageBox.information(self, get_text("menu_save_log"), get_text("connection_no_data_to_save"))
        except Exception as exc:
            QMessageBox.critical(
                self,
                get_text("menu_save_log"),
                get_text("connection_error_prefix").format(error=str(exc)),
            )
        else:
            if saved_path:
                QMessageBox.information(
                    self,
                    get_text("menu_save_log"),
                    get_text("connection_log_saved_prefix").format(path=saved_path),
                )

    def _save_current_log(self) -> str:
        df = self.vm.data_vm.df
        if df is None or df.is_empty():
            raise ValueError("No CAN data to save")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CAN log",
            "",
            "Log files (*.log *.txt);;All files (*)",
        )
        if not path:
            return ""
        if Path(path).suffix == "":
            path = f"{path}.log"

        with open(path, "w", encoding="utf-8") as handle:
            for ts, bus, can_id, data in df.select(["TS", "Bus", "ID", "DATA"]).iter_rows():
                ts_val = float(ts or 0.0)
                bus_val = str(bus or "can0")
                can_id_val = str(can_id or "0")
                data_val = str(data or "").upper()
                handle.write(f"({ts_val:.6f}) {bus_val} {can_id_val}#{data_val}\n")
        return path

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

    def _on_dbc_loaded(self, path: str) -> None:
        self.vm.session_state.add_recent_dbc(path)

    def closeEvent(self, event) -> None:
        self.setEnabled(False)
        self.setCursor(Qt.WaitCursor)
        QApplication.processEvents()
        self.vm.shutdown()
        self.unsetCursor()
        super().closeEvent(event)
