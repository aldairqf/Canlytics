from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from config.app_config import get_text
from utils.can_id import can_id_sort_key


class CanIdJumpDialog(QDialog):
    """Choose an available CAN ID for navigation in the main trace."""

    def __init__(self, can_ids: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(get_text("can_id_jump_title"))
        self.resize(360, 420)
        self._can_ids = sorted(set(can_ids), key=can_id_sort_key)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(get_text("can_id_jump_prompt"), self))
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(get_text("can_id_search_placeholder"))
        layout.addWidget(self.search)
        self.results = QListWidget(self)
        layout.addWidget(self.results, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        self.buttons.button(QDialogButtonBox.Ok).setText(get_text("can_id_jump_select"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._accept_first)
        self.results.itemDoubleClicked.connect(lambda _item: self.accept())
        self._filter("")

    @property
    def selected_can_id(self) -> str | None:
        item = self.results.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def _filter(self, query: str) -> None:
        normalized = query.strip().upper()
        if normalized.startswith("0X"):
            normalized = normalized[2:]
        self.results.clear()
        for can_id in self._can_ids:
            if normalized in can_id.upper().removeprefix("0X"):
                item = QListWidgetItem(can_id)
                item.setData(Qt.UserRole, can_id)
                self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(self.results.count() > 0)

    def _accept_first(self) -> None:
        if self.results.count():
            self.accept()
