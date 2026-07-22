from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from config.theme import get_active_theme
from models.can_send import TransmitEntry, TxLogRecord
from viewmodels.can_send_viewmodel import CanSendViewModel
from views.can_send_entry_dialog import CanSendEntryDialog
from views.icons import icon

_ENTRY_COLUMNS = [
    "can_send_col_enabled", "can_send_col_label", "can_send_col_can_id", "can_send_col_ext",
    "can_send_col_dlc", "can_send_col_data", "can_send_col_source", "can_send_col_mode",
    "can_send_col_interval", "can_send_col_send_now", "can_send_col_periodic",
]
_LOG_COLUMNS = [
    "can_send_log_col_time", "can_send_log_col_label", "can_send_log_col_id",
    "can_send_log_col_data", "can_send_log_col_mode", "can_send_log_col_result",
]


class CanSendWindow(QMainWindow):
    def __init__(self, vm: CanSendViewModel, *, dbc_manager, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("can_send_title"))
        self.resize(1000, 560)

        self._vm = vm
        self._dbc_manager = dbc_manager
        self._periodic_confirmed = False

        toolbar = QToolBar(self)
        self.addToolBar(toolbar)
        self._act_add = toolbar.addAction(icon("plus"), get_text("can_send_add"))
        self._act_edit = toolbar.addAction(icon("pencil"), get_text("can_send_edit"))
        self._act_remove = toolbar.addAction(icon("trash-2"), get_text("can_send_remove"))
        self._act_duplicate = toolbar.addAction(icon("copy"), get_text("can_send_duplicate"))
        self._act_add.triggered.connect(self._on_add)
        self._act_edit.triggered.connect(self._on_edit)
        self._act_remove.triggered.connect(self._on_remove)
        self._act_duplicate.triggered.connect(self._on_duplicate)

        self._not_connected_label = QLabel(get_text("can_send_not_connected"))
        theme = get_active_theme()
        self._not_connected_label.setStyleSheet(f"color: {theme.warn};")
        self._not_connected_label.setVisible(not vm.send_enabled)

        self.table = QTableWidget(0, len(_ENTRY_COLUMNS), self)
        self.table.setHorizontalHeaderLabels([get_text(key) for key in _ENTRY_COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Editing only ever happens through the Edit toolbar action's dialog
        # (validated widgets) -- inline cell text-editing would let free text
        # bypass validation for derived/enum-like columns (Ext, Source, Mode).
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.log_table = QTableWidget(0, len(_LOG_COLUMNS), self)
        self.log_table.setHorizontalHeaderLabels([get_text(key) for key in _LOG_COLUMNS])
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        tabs = QTabWidget(self)
        entries_page = QWidget()
        entries_layout = QVBoxLayout(entries_page)
        entries_layout.addWidget(self._not_connected_label)
        entries_layout.addWidget(self.table)
        tabs.addTab(entries_page, get_text("can_send_tab_entries"))
        tabs.addTab(self.log_table, get_text("can_send_tab_log"))

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(tabs)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        self.table.itemDoubleClicked.connect(lambda _item: self._on_edit())

        vm.entries_changed.connect(self._rebuild_table)
        vm.entry_updated.connect(lambda _entry_id: self._rebuild_table())
        vm.periodic_state_changed.connect(self._on_periodic_state_changed)
        vm.tx_log_appended.connect(self._on_log_appended)
        vm.send_enabled_changed.connect(self._on_send_enabled_changed)

        self._rebuild_table()
        for record in vm.tx_log():
            self._append_log_row(record)

    def _selected_entry_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_add(self) -> None:
        entry = TransmitEntry(entry_id=self._vm.new_entry_id())
        dialog = CanSendEntryDialog(self._dbc_manager, entry, new_entry_id=entry.entry_id, parent=self)
        if dialog.exec():
            self._vm.add_entry(dialog.result_entry())

    def _on_edit(self) -> None:
        entry_id = self._selected_entry_id()
        if entry_id is None:
            return
        entry = next((e for e in self._vm.entries() if e.entry_id == entry_id), None)
        if entry is None:
            return
        dialog = CanSendEntryDialog(self._dbc_manager, entry, new_entry_id=entry_id, parent=self)
        if dialog.exec():
            self._vm.update_entry(dialog.result_entry())

    def _on_remove(self) -> None:
        entry_id = self._selected_entry_id()
        if entry_id is not None:
            self._vm.remove_entry(entry_id)

    def _on_duplicate(self) -> None:
        entry_id = self._selected_entry_id()
        entry = next((e for e in self._vm.entries() if e.entry_id == entry_id), None)
        if entry is None:
            return
        import dataclasses

        clone = dataclasses.replace(entry, entry_id=self._vm.new_entry_id(), label=f"{entry.label} (copy)")
        self._vm.add_entry(clone)

    def _rebuild_table(self) -> None:
        entries = self._vm.entries()
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            enabled_check = QCheckBox()
            enabled_check.setChecked(entry.enabled)
            enabled_check.toggled.connect(lambda checked, eid=entry.entry_id: self._vm.set_enabled(eid, checked))
            self.table.setCellWidget(row, 0, enabled_check)

            label_item = QTableWidgetItem(entry.label)
            label_item.setData(Qt.ItemDataRole.UserRole, entry.entry_id)
            self.table.setItem(row, 1, label_item)
            self.table.setItem(row, 2, QTableWidgetItem(entry.can_id))
            self.table.setItem(row, 3, QTableWidgetItem("29-bit" if entry.extended else "11-bit"))
            self.table.setItem(row, 4, QTableWidgetItem(str(entry.dlc)))
            self.table.setItem(row, 5, QTableWidgetItem(entry.data_hex))
            self.table.setItem(row, 6, QTableWidgetItem(get_text(
                "can_send_entry_source_dbc" if entry.source == "dbc" else "can_send_entry_source_raw"
            )))
            self.table.setItem(row, 7, QTableWidgetItem(get_text(
                "can_send_entry_mode_periodic" if entry.mode == "periodic" else "can_send_entry_mode_single"
            )))
            self.table.setItem(row, 8, QTableWidgetItem(str(entry.interval_ms)))

            send_btn = QPushButton(icon("send"), "")
            send_btn.setEnabled(self._vm.send_enabled)
            send_btn.clicked.connect(lambda _checked=False, eid=entry.entry_id: self._vm.send_now(eid))
            self.table.setCellWidget(row, 9, send_btn)

            periodic_btn = QPushButton()
            periodic_btn.setCheckable(True)
            periodic_btn.setEnabled(self._vm.send_enabled and entry.mode == "periodic")
            periodic_btn.setChecked(self._vm.is_periodic_active(entry.entry_id))
            self._style_periodic_button(periodic_btn, periodic_btn.isChecked())
            periodic_btn.toggled.connect(lambda checked, eid=entry.entry_id: self._on_periodic_toggled(eid, checked))
            self.table.setCellWidget(row, 10, periodic_btn)

    def _style_periodic_button(self, button: QPushButton, active: bool) -> None:
        theme = get_active_theme()
        if active:
            button.setText(get_text("can_send_transmitting"))
            button.setStyleSheet(f"color: {theme.error}; font-weight: bold;")
        else:
            button.setText(get_text("can_send_col_periodic"))
            button.setStyleSheet("")

    def _on_periodic_toggled(self, entry_id: str, checked: bool) -> None:
        if checked and not self._periodic_confirmed:
            reply = QMessageBox.question(
                self,
                get_text("can_send_periodic_confirm_title"),
                get_text("can_send_periodic_confirm_message"),
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._rebuild_table()
                return
            self._periodic_confirmed = True
        self._vm.set_periodic_active(entry_id, checked)

    def _on_periodic_state_changed(self, entry_id: str, active: bool) -> None:
        self._rebuild_table()
        active_count = sum(1 for e in self._vm.entries() if self._vm.is_periodic_active(e.entry_id))
        if active_count:
            self.statusBar().showMessage(f"{active_count} {get_text('can_send_transmitting')}")
        else:
            self.statusBar().clearMessage()

    def _on_send_enabled_changed(self, enabled: bool) -> None:
        self._not_connected_label.setVisible(not enabled)
        self._rebuild_table()

    def _append_log_row(self, record: TxLogRecord) -> None:
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)
        self.log_table.setItem(row, 0, QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(record.ts))))
        self.log_table.setItem(row, 1, QTableWidgetItem(record.label))
        self.log_table.setItem(row, 2, QTableWidgetItem(record.can_id))
        self.log_table.setItem(row, 3, QTableWidgetItem(record.data_hex))
        self.log_table.setItem(row, 4, QTableWidgetItem(record.mode))
        result_text = get_text("can_send_log_ok") if record.success else f"{get_text('can_send_log_failed')}: {record.message}"
        result_item = QTableWidgetItem(result_text)
        if not record.success:
            result_item.setForeground(QColor(get_active_theme().error))
        self.log_table.setItem(row, 5, result_item)
        self.log_table.scrollToBottom()

    def _on_log_appended(self, record: TxLogRecord) -> None:
        self._append_log_row(record)
