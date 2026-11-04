from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from models.plugin import PluginRecord
from viewmodels.plugin_viewmodel import PluginViewModel


class PluginsDialog(QDialog):
    def __init__(self, plugin_vm: PluginViewModel, parent=None):
        super().__init__(parent)
        self.plugin_vm = plugin_vm
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("plugins_title"))
        self.resize(720, 390)

        layout = QVBoxLayout(self)
        explanation = QLabel(get_text("plugins_trust_notice"), self)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels([
            get_text("plugins_column_name"),
            get_text("plugins_column_version"),
            get_text("plugins_column_source"),
            get_text("plugins_column_status"),
            get_text("plugins_column_enabled"),
        ])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, self.table.horizontalHeader().ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.empty_label = QLabel(get_text("plugins_empty"), self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        self.paths_label = QLabel(self)
        self.paths_label.setWordWrap(True)
        layout.addWidget(self.paths_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        records = self.plugin_vm.refresh()
        self.plugin_vm.plugins_changed.connect(self._render)
        self._render(records)

    def _render(self, records: tuple[PluginRecord, ...]) -> None:
        self.table.setRowCount(len(records))
        self.empty_label.setVisible(not records)
        for row, record in enumerate(records):
            self.table.setItem(row, 0, self._item(record.name, record.error))
            self.table.setItem(row, 1, self._item(record.version))
            self.table.setItem(row, 2, self._item(record.source))
            status = record.error or (get_text("plugins_status_active") if record.loaded else get_text("plugins_status_enabled") if record.enabled else get_text("plugins_status_disabled"))
            self.table.setItem(row, 3, self._item(status, record.error))
            checkbox = QCheckBox(self.table)
            checkbox.setChecked(record.enabled)
            checkbox.setEnabled(record.valid)
            checkbox.setAccessibleName(get_text("plugins_toggle_accessible", "Enable {plugin}").format(plugin=record.name))
            checkbox.setToolTip(record.error or get_text("plugins_toggle_tooltip"))
            checkbox.toggled.connect(lambda enabled, plugin_id=record.id: self._toggle(plugin_id, enabled))
            cell = QHBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
            old_wrapper = self.table.cellWidget(row, 4)
            if old_wrapper is not None:
                self.table.removeCellWidget(row, 4)
                old_wrapper.deleteLater()
            wrapper = QWidget(self.table)
            wrapper.setLayout(cell)
            self.table.setCellWidget(row, 4, wrapper)
        directories = "\n".join(str(path) for path in self.plugin_vm.plugin_directories())
        self.paths_label.setText(get_text("plugins_directories", "Plugin folders: {paths}").format(paths=directories))

    @staticmethod
    def _item(text: str, tooltip: str = "") -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if tooltip:
            item.setToolTip(tooltip)
        return item

    def _toggle(self, plugin_id: str, enabled: bool) -> None:
        self.plugin_vm.set_enabled(plugin_id, enabled)
