from PySide6.QtCore import Qt, QThread, QObject, Signal as QtSignal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QFileDialog,
    QDialogButtonBox,
    QMessageBox,
    QProgressDialog,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QAbstractItemView,
)

from services.dbc_manager import DbcManager
from config.app_config import get_option, get_text


class DbcManagerDialog(QDialog):
    def __init__(self, dbc_manager: DbcManager, parent=None):
        super().__init__(parent)
        self.dbc_manager = dbc_manager
        self._updating = False
        self.setWindowTitle(get_text("dbc_manager_title"))
        self.resize(520, 360)

        self.empty_label = QLabel(get_text("dbc_empty"))
        self.empty_label.setAlignment(Qt.AlignCenter)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            get_text("dbc_enable_header"),
            get_text("dbc_name_header"),
            get_text("dbc_type_header"),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setDragDropMode(QAbstractItemView.InternalMove)
        self.table.setDragDropOverwriteMode(False)
        self.table.setDropIndicatorShown(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.model().rowsMoved.connect(self._on_rows_moved)

        self.load_button = QPushButton(get_text("dbc_load"))
        self.load_button.clicked.connect(self._on_load_clicked)

        self.delete_button = QPushButton(get_text("dbc_delete"))
        self.delete_button.clicked.connect(self._on_delete_clicked)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.table)

        controls = QHBoxLayout()
        controls.addWidget(self.load_button)
        controls.addWidget(self.delete_button)
        controls.addStretch()
        layout.addLayout(controls)
        layout.addWidget(buttons)

        self._load_thread = None
        self._load_worker = None
        self.dbc_manager.entries_changed.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        self._updating = True
        entries = self.dbc_manager.list_entries()
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(enabled_item.flags() | Qt.ItemIsUserCheckable)
            enabled_item.setCheckState(Qt.Checked if entry.active else Qt.Unchecked)
            enabled_item.setData(Qt.UserRole, entry.name)
            enabled_item.setToolTip(entry.path)
            self.table.setItem(row, 0, enabled_item)

            name_item = QTableWidgetItem(entry.name)
            name_item.setToolTip(entry.path)
            self.table.setItem(row, 1, name_item)

            type_combo = QComboBox()
            type_combo.addItems(get_option("dbc_modes", []))
            type_combo.setCurrentText(entry.mode)
            type_combo.currentTextChanged.connect(
                lambda mode, name=entry.name: self._on_mode_changed(name, mode)
            )
            self.table.setCellWidget(row, 2, type_combo)

        has_entries = bool(entries)
        self.empty_label.setVisible(not has_entries)
        self.table.setVisible(has_entries)
        self.delete_button.setEnabled(has_entries)
        self.table.blockSignals(False)
        self._updating = False

    def _on_load_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            get_text("dbc_load_title"),
            "",
            get_text("dbc_files_filter"),
        )
        if not path:
            return
        self._start_dbc_load(path)

    def _on_delete_clicked(self):
        row = self.table.currentRow()
        if row < 0:
            return
        name_item = self.table.item(row, 1)
        if not name_item:
            return
        self.dbc_manager.remove_entry(name_item.text())

    def _start_dbc_load(self, path: str):
        self.setEnabled(False)
        self._loading = QProgressDialog(
            get_text("dbc_loading"), "", 0, 0, self
        )
        self._loading.setWindowTitle(get_text("dbc_loading_title"))
        self._loading.setWindowModality(Qt.ApplicationModal)
        self._loading.setCancelButton(None)
        self._loading.show()

        self._load_worker = DbcLoadWorker(path)
        self._load_thread = QThread()
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.finished.connect(self._on_dbc_loaded)
        self._load_worker.failed.connect(self._on_dbc_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._cleanup_load_thread)
        self._load_thread.start()

    def _on_dbc_loaded(self, path: str, db):
        try:
            self.dbc_manager.add_loaded_db(path, db)
        except Exception as exc:
            self._show_load_error(exc)
        self._finish_load()

    def _on_dbc_failed(self, message: str):
        self._show_load_error(message)
        self._finish_load()

    def _show_load_error(self, exc):
        QMessageBox.warning(
            self,
            get_text("dbc_load_failed_title"),
            get_text("dbc_load_failed_message").format(error=exc),
        )

    def _finish_load(self):
        if self._loading:
            self._loading.close()
            self._loading = None
        self.setEnabled(True)

    def _cleanup_load_thread(self):
        if self._load_worker:
            self._load_worker.deleteLater()
            self._load_worker = None
        if self._load_thread:
            self._load_thread.deleteLater()
            self._load_thread = None

    def closeEvent(self, event):
        if self._load_thread and self._load_thread.isRunning():
            self._load_thread.quit()
            self._load_thread.wait(2000)
        super().closeEvent(event)

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._updating:
            return
        if item.column() != 0:
            return
        names = set()
        for row in range(self.table.rowCount()):
            enabled_item = self.table.item(row, 0)
            if enabled_item and enabled_item.checkState() == Qt.Checked:
                name = enabled_item.data(Qt.UserRole)
                if name:
                    names.add(name)
        self.dbc_manager.set_active(names)

    def _on_mode_changed(self, name: str, mode: str):
        if self._updating:
            return
        self.dbc_manager.set_entry_mode(name, mode)

    def _on_rows_moved(self, *_args):
        if self._updating:
            return
        order = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 1)
            if name_item:
                order.append(name_item.text())
        if order:
            self.dbc_manager.set_order(order)


class DbcLoadWorker(QObject):
    finished = QtSignal(str, object)
    failed = QtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        try:
            db = DbcManager()._load_database(self._path)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(self._path, db)
