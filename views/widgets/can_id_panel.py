from __future__ import annotations

from typing import Iterable, Set

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
)

from services.dbc_manager import DbcManager
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from config.app_config import get_text


class CanIdPanelWidget(QWidget):
    selected_ids_changed = QtSignal(object)
    expand_all_clicked = QtSignal()
    collapse_all_clicked = QtSignal()
    interpret_toggled = QtSignal(bool)

    def __init__(self, dbc_manager: DbcManager, interpret_vm: InterpretationViewModel, parent: QWidget | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._interpret_vm = interpret_vm

        self._current_can_ids: list[str] = []
        self._items_by_id: dict[str, QListWidgetItem] = {}

        self.btn_all = QPushButton(get_text("select_all"))
        self.btn_none = QPushButton(get_text("select_none"))

        self.interpret_checkbox = QCheckBox(get_text("interpret_frames"))
        self.interpret_checkbox.setToolTip(get_text("interpret_tooltip"))

        self.btn_expand = QPushButton(get_text("expand_all"))
        self.btn_collapse = QPushButton(get_text("collapse_all"))

        self.can_list = QListWidget()

        layout = QVBoxLayout(self)
        layout.addWidget(self.btn_all)
        layout.addWidget(self.btn_none)
        layout.addWidget(self.interpret_checkbox)
        layout.addWidget(self.btn_expand)
        layout.addWidget(self.btn_collapse)
        layout.addWidget(self.can_list)

        self.btn_all.clicked.connect(self._select_all)
        self.btn_none.clicked.connect(self._select_none)
        self.btn_expand.clicked.connect(self.expand_all_clicked.emit)
        self.btn_collapse.clicked.connect(self.collapse_all_clicked.emit)

        self.can_list.itemChanged.connect(self._emit_selected_ids)
        self.interpret_checkbox.toggled.connect(self.interpret_toggled.emit)

        self._interpret_vm.available_changed.connect(self.set_interpret_available)
        self._interpret_vm.enabled_changed.connect(lambda _: self.refresh_labels())

        self.set_interpret_available(self._interpret_vm.available)

    def set_interpret_available(self, enabled: bool) -> None:
        self.interpret_checkbox.setEnabled(enabled)
        self.btn_expand.setEnabled(enabled)
        self.btn_collapse.setEnabled(enabled)

    def set_interpret_checked(self, checked: bool) -> None:
        self.interpret_checkbox.blockSignals(True)
        self.interpret_checkbox.setChecked(checked)
        self.interpret_checkbox.blockSignals(False)

    def set_can_ids(self, ids: Iterable[str]) -> None:
        ids_list = list(ids)
        ids_set = set(ids_list)

        prev_selected = self.selected_ids() if self._current_can_ids else set()
        self._current_can_ids = ids_list

        self.can_list.blockSignals(True)
        self.can_list.setUpdatesEnabled(False)

        removed = [cid for cid in list(self._items_by_id.keys()) if cid not in ids_set]
        for cid in removed:
            item = self._items_by_id.pop(cid)
            row = self.can_list.row(item)
            if row >= 0:
                self.can_list.takeItem(row)

        interpret_enabled = self._interpret_vm.enabled

        for cid in ids_list:
            item = self._items_by_id.get(cid)
            if item is None:
                display = cid
                if interpret_enabled:
                    name = self._dbc_manager.resolve_message_name(cid)
                    if name:
                        display = f"{cid}  {name}"

                item = QListWidgetItem(display)
                item.setData(Qt.UserRole, cid)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if (not prev_selected or cid in prev_selected) else Qt.Unchecked)

                self.can_list.addItem(item)
                self._items_by_id[cid] = item
            else:
                display = cid
                if interpret_enabled:
                    name = self._dbc_manager.resolve_message_name(cid)
                    if name:
                        display = f"{cid}  {name}"
                item.setText(display)

        self.can_list.setUpdatesEnabled(True)
        self.can_list.blockSignals(False)

        self.selected_ids_changed.emit(self.selected_ids())

    def refresh_labels(self) -> None:
        if not self._current_can_ids:
            return

        interpret_enabled = self._interpret_vm.enabled

        self.can_list.setUpdatesEnabled(False)
        for cid, item in self._items_by_id.items():
            display = cid
            if interpret_enabled:
                name = self._dbc_manager.resolve_message_name(cid)
                if name:
                    display = f"{cid}  {name}"
            item.setText(display)
        self.can_list.setUpdatesEnabled(True)

    def selected_ids(self) -> Set[str]:
        selected = set()
        for i in range(self.can_list.count()):
            item = self.can_list.item(i)
            if item.checkState() == Qt.Checked:
                cid = item.data(Qt.UserRole)
                if cid is not None:
                    selected.add(cid)
        return selected

    def _select_all(self) -> None:
        self._set_all(Qt.Checked)

    def _select_none(self) -> None:
        self._set_all(Qt.Unchecked)

    def _set_all(self, state: Qt.CheckState) -> None:
        self.can_list.blockSignals(True)
        for i in range(self.can_list.count()):
            self.can_list.item(i).setCheckState(state)
        self.can_list.blockSignals(False)
        self._emit_selected_ids()

    def _emit_selected_ids(self) -> None:
        self.selected_ids_changed.emit(self.selected_ids())
