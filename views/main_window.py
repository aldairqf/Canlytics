from PySide6.QtWidgets import (
    QMainWindow,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QProgressDialog,
    QCheckBox,
    QMenu,
    QStyle,
)
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtCore import Qt, QThread, QObject, QTimer, Signal as QtSignal
from PySide6.QtGui import QColor

from views.table.table_view import DataTableView
from views.plot.plot_window import PlotWindow

from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.table_filter_viewmodel import TableFilterViewModel
from viewmodels.table_viewmodel import TableViewModel
from viewmodels.plot_viewmodel import PlotViewModel
from viewmodels.log_loader_worker import LogLoaderWorker
from views.table.table_model import TableModel
from views.signal.signal_view import ViewSignal
from core.signal import Signal
from core.dbc_manager import DbcManager
from views.dbc.dbc_manager_dialog import DbcManagerDialog
import polars as pl

DEFAULT_COLUMNS = [
    "TS", "Bus", "ID", "LEN", "DATA",
    "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7",
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("CAN Log Viewer")
        self.resize(1200, 700)

        self.data_vm = LogDataViewModel()
        self.filter_vm = TableFilterViewModel()
        self.table_model = TableModel(DEFAULT_COLUMNS)
        self.table_vm = TableViewModel(self.table_model)
        self.table = DataTableView(self.table_model)
        self.dbc_manager = DbcManager()

        self.data_vm.dataframe_changed.connect(self.filter_vm.set_dataframe)
        self.data_vm.can_ids_changed.connect(self._populate_can_ids)
        self.filter_vm.dataframe_changed.connect(self.table_vm.set_dataframe)
        self.dbc_manager.entries_changed.connect(self._refresh_can_id_labels)
        self.dbc_manager.entries_changed.connect(self._update_interpret_enabled)

        self.can_list = QListWidget()
        self.can_list.itemChanged.connect(self._on_can_id_toggled)

        self.btn_all = QPushButton("Select all")
        self.btn_none = QPushButton("Select none")
        self.btn_all.clicked.connect(self._select_all)
        self.btn_none.clicked.connect(self._select_none)

        self.interpret_checkbox = QCheckBox("Interpret frames")
        self.interpret_checkbox.toggled.connect(self._on_interpret_toggled)
        self.interpret_checkbox.setToolTip("Load/enable a DBC to interpret frames")

        self.btn_expand = QPushButton("Expand all")
        self.btn_collapse = QPushButton("Collapse all")
        self.btn_expand.clicked.connect(self._expand_all_rows)
        self.btn_collapse.clicked.connect(self._collapse_all_rows)

        side_layout = QVBoxLayout()
        side_layout.addWidget(self.btn_all)
        side_layout.addWidget(self.btn_none)
        side_layout.addWidget(self.interpret_checkbox)
        side_layout.addWidget(self.btn_expand)
        side_layout.addWidget(self.btn_collapse)
        side_layout.addWidget(self.can_list)

        side_widget = QWidget()
        side_widget.setLayout(side_layout)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.addWidget(side_widget, 1)
        layout.addWidget(self.table, 4)

        self.setCentralWidget(container)

        self._plot_windows = {}
        self._load_thread = None
        self._load_worker = None
        self._progress_dialog = None
        self._current_can_ids: list[str] = []
        self._last_plot_window = None
        self._timezone_mode = "none"
        self._interpret_loading = None

        self._interpret_thread = None
        self._interpret_worker = None
        self._rows_have_custom_heights = False

        self._setup_menu()
        self.table.decode_context_requested.connect(self._on_decode_context)
        self.table.row_toggle_requested.connect(self._toggle_row_expand)
        self._update_interpret_enabled()

    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        load_action = QAction("Load Log", self)
        load_action.triggered.connect(self._on_load_log)
        file_menu.addAction(load_action)

        append_action = QAction("Append Log", self)
        append_action.triggered.connect(self._on_append_log)
        file_menu.addAction(append_action)

        clear_action = QAction("Clear log", self)
        clear_action.triggered.connect(self._clear_log)
        file_menu.addAction(clear_action)

        load_dbc_action = QAction("Load DBC...", self)
        load_dbc_action.triggered.connect(self._open_dbc_manager)
        file_menu.addAction(load_dbc_action)

        settings_menu = menubar.addMenu("Settings")
        normalize = QAction("Normalize timestamp", self, checkable=True)
        normalize.triggered.connect(self.data_vm.set_normalize)
        settings_menu.addAction(normalize)

        time_menu = settings_menu.addMenu("Time axis")
        time_group = QActionGroup(self)
        time_group.setExclusive(True)

        raw_action = QAction("Raw seconds", self, checkable=True)
        raw_action.triggered.connect(lambda: self._set_timezone("none"))
        time_group.addAction(raw_action)
        time_menu.addAction(raw_action)

        utc_action = QAction("UTC", self, checkable=True)
        utc_action.triggered.connect(lambda: self._set_timezone("UTC"))
        time_group.addAction(utc_action)
        time_menu.addAction(utc_action)

        lima_action = QAction("America / Lima", self, checkable=True)
        lima_action.triggered.connect(lambda: self._set_timezone("America/Lima"))
        time_group.addAction(lima_action)
        time_menu.addAction(lima_action)

        tokyo_action = QAction("Asia / Tokyo", self, checkable=True)
        tokyo_action.triggered.connect(lambda: self._set_timezone("Asia/Tokyo"))
        time_group.addAction(tokyo_action)
        time_menu.addAction(tokyo_action)

        action_map = {
            "none": raw_action,
            "UTC": utc_action,
            "America/Lima": lima_action,
            "Asia/Tokyo": tokyo_action,
        }
        action_map.get(self._timezone_mode, raw_action).setChecked(True)

        tools_menu = menubar.addMenu("Tools")
        add_plot = QAction("Add new graphic window", self)
        add_plot.triggered.connect(self._open_plot_window)
        tools_menu.addAction(add_plot)

    def _open_plot_window(self):
        df = self.data_vm.df
        if df is None or df.is_empty():
            df = pl.DataFrame()
        plot_vm = PlotViewModel(df)
        self.data_vm.dataframe_changed.connect(plot_vm.set_dataframe)
        win = PlotWindow(
            plot_vm,
            dbc_manager=self.dbc_manager,
            timezone_mode=self._timezone_mode,
        )
        win.closed.connect(lambda: self._on_plot_closed(win))
        self._plot_windows[win] = plot_vm
        self._last_plot_window = win
        win.show()
        return win, plot_vm

    def _on_plot_closed(self, window):
        plot_vm = self._plot_windows.pop(window, None)
        if plot_vm:
            try:
                self.data_vm.dataframe_changed.disconnect(plot_vm.set_dataframe)
            except (TypeError, RuntimeError):
                pass
        if self._last_plot_window is window:
            self._last_plot_window = next(iter(self._plot_windows), None)

    def _on_load_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load CAN log",
            "",
            "Log files (*.log *.txt);;All files (*)",
        )
        if path:
            self._start_log_load(path, mode="load")

    def _on_append_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Append CAN log",
            "",
            "Log files (*.log *.txt);;All files (*)",
        )
        if path:
            self._start_log_load(path, mode="append")

    def _clear_log(self):
        self.data_vm.clear()
        self._refresh_row_heights()

    def _open_dbc_manager(self):
        dlg = DbcManagerDialog(self.dbc_manager, parent=self)
        dlg.exec()

    def _set_timezone(self, tz: str):
        self._timezone_mode = tz
        for window in self._plot_windows:
            window._set_timezone(tz)

    def _start_log_load(self, path: str, mode: str):
        if self._load_thread is not None:
            return

        self._progress_dialog = QProgressDialog(
            "Loading CAN log...", "Cancel", 0, 0, self
        )
        self._progress_dialog.setWindowTitle("Loading")
        self._progress_dialog.setWindowModality(Qt.ApplicationModal)
        self._progress_dialog.canceled.connect(self._on_cancel_load)
        self._progress_dialog.show()

        self._load_thread = QThread()
        self._load_worker = LogLoaderWorker(path, self.data_vm.normalize, mode)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.canceled.connect(self._on_load_canceled)
        self._load_worker.failed.connect(self._on_load_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.canceled.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._cleanup_load_worker)
        self._load_thread.start()

    def _on_cancel_load(self):
        if self._load_worker:
            self._progress_dialog.setLabelText("Canceling...")
            self._load_worker.cancel()

    def _on_load_finished(self, path: str, df: pl.DataFrame, is_full_load: bool):
        if self._load_worker and self._load_worker.cancel_requested:
            return
        if is_full_load:
            self.data_vm.replace_log(path, df)
        else:
            self.data_vm.append_df(df)

    def _on_load_canceled(self):
        pass

    def _on_load_failed(self, message: str):
        if self._progress_dialog:
            self._progress_dialog.setLabelText(f"Failed: {message}")

    def _cleanup_load_worker(self):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        if self._load_worker:
            self._load_worker.deleteLater()
            self._load_worker = None
        if self._load_thread:
            self._load_thread.deleteLater()
            self._load_thread = None

    def _populate_can_ids(self, ids, selected_ids: set[str] | None = None):
        self._current_can_ids = list(ids)
        selected_ids = set(ids) if selected_ids is None else selected_ids
        self.can_list.blockSignals(True)
        self.can_list.clear()
        for can_id in ids:
            display = can_id
            if self._interpret_enabled:
                message_name = self.dbc_manager.resolve_message_name(can_id)
                if message_name:
                    display = f"{can_id}  {message_name}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, can_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if can_id in selected_ids else Qt.Unchecked
            )
            self.can_list.addItem(item)
        self.can_list.blockSignals(False)
        self.filter_vm.set_selected_ids(selected_ids)

    def _select_all(self):
        self._set_all(Qt.Checked)

    def _select_none(self):
        self._set_all(Qt.Unchecked)

    def _set_all(self, state):
        self.can_list.blockSignals(True)
        for i in range(self.can_list.count()):
            self.can_list.item(i).setCheckState(state)
        self.can_list.blockSignals(False)
        self._on_can_id_toggled()

    def _on_can_id_toggled(self):
        selected = {
            self.can_list.item(i).data(Qt.UserRole)
            for i in range(self.can_list.count())
            if self.can_list.item(i).checkState() == Qt.Checked
        }
        selected.discard(None)
        self.filter_vm.set_selected_ids(selected)

    def _refresh_can_id_labels(self):
        if not self._current_can_ids:
            return
        selected = {
            self.can_list.item(i).data(Qt.UserRole)
            for i in range(self.can_list.count())
            if self.can_list.item(i).checkState() == Qt.Checked
        }
        selected.discard(None)
        self._populate_can_ids(self._current_can_ids, selected_ids=selected)

    def _update_interpret_enabled(self):
        enabled = bool(self.dbc_manager.active_entries())
        self.interpret_checkbox.setEnabled(enabled)
        self.btn_expand.setEnabled(enabled)
        self.btn_collapse.setEnabled(enabled)
        if not enabled:
            self.interpret_checkbox.setChecked(False)
        self.table_vm.set_decode_context(self.dbc_manager, self._interpret_enabled)

    @property
    def _interpret_enabled(self) -> bool:
        return self.interpret_checkbox.isChecked()

    def _on_interpret_toggled(self, checked: bool):
        if checked:
            self._start_interpret_load()
        else:
            self.table_vm.set_decode_context(self.dbc_manager, False)
            self._refresh_can_id_labels()
            self._refresh_row_heights()

    def _on_decode_context(self, row: int, line_index: int, global_pos):
        if not self._interpret_enabled:
            return
        item = self.table_model.get_decode_item_for_line(row, line_index)
        if not item:
            return
        signal_def = item.get("signal_def")
        if not signal_def:
            return
        row_can_id = self.table_model.get_row_can_id(row)
        if row_can_id:
            signal_def = {**signal_def, "can_id": row_can_id}
        menu = QMenu(self)
        add_new = menu.addAction("Add new graph")
        add_last = menu.addAction("Add last graph")
        action = menu.exec(global_pos)
        if action == add_new:
            self._add_graph_from_signal(signal_def, use_last=False)
        elif action == add_last:
            self._add_graph_from_signal(signal_def, use_last=True)

    def _add_graph_from_signal(self, signal_def: dict, use_last: bool):
        if use_last and self._last_plot_window in self._plot_windows:
            plot_vm = self._plot_windows[self._last_plot_window]
            win = self._last_plot_window
        else:
            win, plot_vm = self._open_plot_window()

        base_name = signal_def.get("name", "Signal")
        name = self._unique_signal_name(plot_vm, base_name)
        sig = Signal(**{**signal_def, "name": name})
        view_signal = ViewSignal(
            signal=sig,
            color=QColor("cyan"),
            line_style="Solid",
            line_width=2,
        )
        plot_vm.upsert_signal(view_signal)
        self._last_plot_window = win

    @staticmethod
    def _unique_signal_name(plot_vm: PlotViewModel, base: str) -> str:
        name = base
        index = 1
        while name in plot_vm.signals:
            name = f"{base}_{index}"
            index += 1
        return name

    def _expand_all_rows(self):
        if not self._interpret_enabled:
            return
        self.table_vm.set_all_expanded(True)
        self._refresh_row_heights(expanded=True)

    def _collapse_all_rows(self):
        self.table_vm.set_all_expanded(False)
        self._refresh_row_heights(expanded=False)

    def _row_base_height(self) -> int:
            line_h = max(1, self.table.fontMetrics().lineSpacing())
            vpad = self.table.style().pixelMetric(QStyle.PM_FocusFrameVMargin, None, self.table)
            vpad = 0 if vpad < 0 else vpad
            return max(20, line_h + 2 * vpad)

    def _refresh_row_heights(self, expanded: bool | None = None):
        base_height = self._row_base_height()
        self.table.verticalHeader().setDefaultSectionSize(base_height)

        total = self.table_model.rowCount()
        chunk = 500

        if expanded is True:
            self._rows_have_custom_heights = True

            def step_expand(start: int):
                end = min(total, start + chunk)
                for row in range(start, end):
                    line_count = self.table_model.get_decode_line_count(row)
                    height = base_height * (1 + max(0, line_count))
                    self.table.setRowHeight(row, height)
                if end < total:
                    QTimer.singleShot(0, lambda: step_expand(end))

            step_expand(0)
            return

        if not self._rows_have_custom_heights:
            return

        def step_reset(start: int):
            end = min(total, start + chunk)
            for row in range(start, end):
                self.table.setRowHeight(row, base_height)
            if end < total:
                QTimer.singleShot(0, lambda: step_reset(end))
            else:
                self._rows_have_custom_heights = False

        step_reset(0)

    def _toggle_row_expand(self, row: int):
        self.table_vm.toggle_row_expanded(row)
        base_height = self._row_base_height()
        line_count = self.table_model.get_decode_line_count(row)
        height = base_height * (1 + max(0, line_count))
        self.table.setRowHeight(row, height)
        self._rows_have_custom_heights = True

    def _start_interpret_load(self):
        if not self._interpret_enabled:
            return
        if self._interpret_thread is not None and self._interpret_thread.isRunning():
            return

        self.interpret_checkbox.setEnabled(False)
        self._interpret_loading = QProgressDialog(
            "Preparing interpretation...", "", 0, 0, self
        )
        self._interpret_loading.setWindowTitle("Interpret Frames")
        self._interpret_loading.setWindowModality(Qt.ApplicationModal)
        self._interpret_loading.setCancelButton(None)
        self._interpret_loading.show()

        self._interpret_worker = InterpretWorker()
        self._interpret_thread = QThread(self)
        self._interpret_worker.moveToThread(self._interpret_thread)

        self._interpret_thread.started.connect(self._interpret_worker.run)
        self._interpret_worker.finished.connect(self._interpret_thread.quit)
        self._interpret_worker.finished.connect(self._finish_interpret_load)
        self._interpret_thread.finished.connect(self._cleanup_interpret_worker)

        self._interpret_thread.start()

    def _cleanup_interpret_worker(self):
        if self._interpret_worker:
            self._interpret_worker.deleteLater()
            self._interpret_worker = None
        if self._interpret_thread:
            self._interpret_thread.deleteLater()
            self._interpret_thread = None

    def _finish_interpret_load(self):
        if self._interpret_loading:
            self._interpret_loading.close()
            self._interpret_loading = None
        self.interpret_checkbox.setEnabled(True)
        self.table_vm.set_decode_context(self.dbc_manager, True)
        self._refresh_can_id_labels()
        self._refresh_row_heights()

    def closeEvent(self, event):
        if self._load_thread is not None and self._load_thread.isRunning():
            if self._load_worker is not None:
                self._load_worker.cancel()
            self._load_thread.quit()
            self._load_thread.wait(2000)

        if self._interpret_thread is not None and self._interpret_thread.isRunning():
            self._interpret_thread.quit()
            self._interpret_thread.wait(2000)

        super().closeEvent(event)


class InterpretWorker(QObject):
    finished = QtSignal()

    def run(self):
        self.finished.emit()
