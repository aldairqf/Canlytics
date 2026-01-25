from __future__ import annotations

from typing import Iterable, Optional, Set

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
)

from core.dbc_manager import DbcManager
from viewmodels.interpretation_viewmodel import InterpretationViewModel


class CanIdPanelWidget(QWidget):

    selected_ids_changed = QtSignal(object)  # set[str]
    expand_all_clicked = QtSignal()
    collapse_all_clicked = QtSignal()
    interpret_toggled = QtSignal(bool)

    def __init__(self, dbc_manager: DbcManager, interpret_vm: InterpretationViewModel, parent: QWidget | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._interpret_vm = interpret_vm

        self._current_can_ids: list[str] = []

        self.btn_all = QPushButton("Select all")
        self.btn_none = QPushButton("Select none")

        self.interpret_checkbox = QCheckBox("Interpret frames")
        self.interpret_checkbox.setToolTip("Load/enable a DBC to interpret frames")

        self.btn_expand = QPushButton("Expand all")
        self.btn_collapse = QPushButton("Collapse all")

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
        prev_selected = self.selected_ids() if self._current_can_ids else None
        self._current_can_ids = ids_list

        selected = prev_selected if prev_selected is not None else set(ids_list)
        selected = selected.intersection(ids_list) if prev_selected is not None else selected

        self._populate(ids_list, selected_ids=selected)
        self.selected_ids_changed.emit(self.selected_ids())

    def refresh_labels(self) -> None:
        if not self._current_can_ids:
            return
        selected = self.selected_ids()
        self._populate(self._current_can_ids, selected_ids=selected)

    def selected_ids(self) -> Set[str]:
        selected = {
            self.can_list.item(i).data(Qt.UserRole)
            for i in range(self.can_list.count())
            if self.can_list.item(i).checkState() == Qt.Checked
        }
        selected.discard(None)
        return selected

    def _populate(self, ids: list[str], selected_ids: Set[str]) -> None:
        self.can_list.blockSignals(True)
        self.can_list.clear()

        interpret_enabled = self._interpret_vm.enabled

        for can_id in ids:
            display = can_id
            if interpret_enabled:
                name = self._dbc_manager.resolve_message_name(can_id)
                if name:
                    display = f"{can_id}  {name}"

            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, can_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if can_id in selected_ids else Qt.Unchecked)
            self.can_list.addItem(item)

        self.can_list.blockSignals(False)

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