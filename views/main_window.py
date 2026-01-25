from __future__ import annotations

import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QFileDialog, QProgressDialog

from core.dbc_manager import DbcManager
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.table_filter_viewmodel import TableFilterViewModel
from viewmodels.table_viewmodel import TableViewModel
from viewmodels.log_load_viewmodel import LogLoadViewModel
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from views.dbc.dbc_manager_dialog import DbcManagerDialog
from views.main_window_view import MainWindowView
from views.menu.main_menu_factory import build_main_menu
from views.plot.plot_window_manager import PlotWindowManager
from views.table.table_model import TableModel
from views.table.row_height_manager import RowHeightManager

DEFAULT_COLUMNS = [
    "TS", "Bus", "ID", "LEN", "DATA",
    "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7",
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CAN Log Viewer")
        self.resize(1200, 700)

        self._timezone_mode = "none"
        self._load_progress: QProgressDialog | None = None

        # core + VMs
        self.dbc_manager = DbcManager()

        self.data_vm = LogDataViewModel()
        self.filter_vm = TableFilterViewModel()
        self.table_model = TableModel(DEFAULT_COLUMNS)
        self.table_vm = TableViewModel(self.table_model)

        self.log_load_vm = LogLoadViewModel(self)
        self.interpret_vm = InterpretationViewModel(self.dbc_manager, self.table_vm, parent=self)

        # bindings entre VMs existentes
        self.data_vm.dataframe_changed.connect(self.filter_vm.set_dataframe)
        self.filter_vm.dataframe_changed.connect(self.table_vm.set_dataframe)

        # view
        self.view = MainWindowView(
            self.table_model,
            dbc_manager=self.dbc_manager,
            interpret_vm=self.interpret_vm,
            parent=self,
        )
        self.setCentralWidget(self.view)

        # helpers de UI (en views/)
        self.row_heights = RowHeightManager(self.view.table, self.table_model, self.table_vm)
        self.plot_manager = PlotWindowManager(
            self,
            data_vm=self.data_vm,
            dbc_manager=self.dbc_manager,
            table_model=self.table_model,
            get_timezone=lambda: self._timezone_mode,
            interpret_enabled=lambda: self.interpret_vm.enabled,
        )

        # UI -> VM
        self.view.panel.selected_ids_changed.connect(self.filter_vm.set_selected_ids)
        self.view.panel.interpret_toggled.connect(self.interpret_vm.set_enabled)

        self.view.panel.expand_all_clicked.connect(self._on_expand_all)
        self.view.panel.collapse_all_clicked.connect(self._on_collapse_all)

        # VM -> UI
        self.data_vm.can_ids_changed.connect(self.view.panel.set_can_ids)

        self.interpret_vm.enabled_changed.connect(self._on_interpret_enabled_changed)
        self.interpret_vm.available_changed.connect(lambda _: self.view.panel.refresh_labels())

        # tabla
        self.view.table.decode_context_requested.connect(self.plot_manager.on_decode_context)
        self.view.table.row_toggle_requested.connect(self.row_heights.toggle_row)

        # carga de log
        self.log_load_vm.load_started.connect(self._show_load_progress)
        self.log_load_vm.load_finished.connect(self._hide_load_progress)
        self.log_load_vm.load_failed.connect(self._set_load_failed_text)
        self.log_load_vm.loaded.connect(self._apply_loaded_df)

        # menú
        build_main_menu(
            self,
            data_vm=self.data_vm,
            on_load=self._pick_load_log,
            on_append=self._pick_append_log,
            on_clear=self._clear_log,
            on_open_dbc=self._open_dbc_manager,
            on_open_plot=lambda: self.plot_manager.open_plot_window(),
            set_timezone=self._set_timezone,
            get_timezone=lambda: self._timezone_mode,
        )

    def _set_timezone(self, tz: str) -> None:
        self._timezone_mode = tz
        self.plot_manager.set_timezone(tz)

    def _pick_load_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load CAN log", "", "Log files (*.log *.txt);;All files (*)"
        )
        if path:
            self.log_load_vm.start(path=path, normalize=self.data_vm.normalize, mode="load")

    def _pick_append_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Append CAN log", "", "Log files (*.log *.txt);;All files (*)"
        )
        if path:
            self.log_load_vm.start(path=path, normalize=self.data_vm.normalize, mode="append")

    def _apply_loaded_df(self, path: str, df: pl.DataFrame, is_full_load: bool) -> None:
        if is_full_load:
            self.data_vm.replace_log(path, df)
        else:
            self.data_vm.append_df(df)

    def _show_load_progress(self, _path: str) -> None:
        self._load_progress = QProgressDialog("Loading CAN log...", "Cancel", 0, 0, self)
        self._load_progress.setWindowTitle("Loading")
        self._load_progress.setWindowModality(Qt.ApplicationModal)
        self._load_progress.canceled.connect(self.log_load_vm.cancel)
        self._load_progress.show()

    def _set_load_failed_text(self, message: str) -> None:
        if self._load_progress:
            self._load_progress.setLabelText(f"Failed: {message}")

    def _hide_load_progress(self) -> None:
        if self._load_progress:
            self._load_progress.close()
            self._load_progress = None

    def _open_dbc_manager(self) -> None:
        dlg = DbcManagerDialog(self.dbc_manager, parent=self)
        dlg.exec()

    def _clear_log(self) -> None:
        self.data_vm.clear()
        self.row_heights.refresh()

    def _on_interpret_enabled_changed(self, enabled: bool) -> None:
        self.view.panel.set_interpret_checked(enabled)
        self.view.panel.refresh_labels()
        self.row_heights.refresh()

    def _on_expand_all(self) -> None:
        if self.interpret_vm.enabled:
            self.row_heights.expand_all()

    def _on_collapse_all(self) -> None:
        self.row_heights.collapse_all()

    def closeEvent(self, event) -> None:
        self.log_load_vm.shutdown()
        self.interpret_vm.shutdown()
        super().closeEvent(event)