from __future__ import annotations

from typing import Callable, Iterable, Set

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QGroupBox,
    QLineEdit,
)

from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from config.app_config import get_text
from utils.can_id import can_id_sort_key
from views.widgets.time_filter_widget import TimeFilterWidget


class CanIdPanelWidget(QWidget):
    selected_ids_changed = QtSignal(object)
    expand_all_clicked = QtSignal()
    collapse_all_clicked = QtSignal()
    interpret_toggled = QtSignal(bool)
    time_range_changed = QtSignal(object, object)

    def __init__(
        self,
        resolve_message_name: Callable[[str], str | None],
        interpret_vm: InterpretationViewModel,
        time_config_vm: TimeConfigViewModel,
        *,
        show_time_filter: bool = True,
        show_interpret_controls: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._resolve_message_name = resolve_message_name
        self._interpret_vm = interpret_vm
        self._time_config_vm = time_config_vm

        self._current_can_ids: list[str] = []
        self._items_by_id: dict[str, QListWidgetItem] = {}
        self._last_emitted_selected_ids: set[str] = set()

        self.btn_all = QPushButton(get_text("select_all"))
        self.btn_none = QPushButton(get_text("select_none"))

        self.interpret_checkbox = QCheckBox(get_text("interpret_frames"))
        self.interpret_checkbox.setToolTip(get_text("interpret_tooltip"))

        self.btn_expand = QPushButton(get_text("expand_all"))
        self.btn_collapse = QPushButton(get_text("collapse_all"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(get_text("can_id_search_placeholder"))
        self.time_filter = TimeFilterWidget(self._time_config_vm, parent=self) if show_time_filter else None

        self.can_list = QListWidget()

        layout = QVBoxLayout(self)
        if self.time_filter is not None:
            layout.addWidget(self.time_filter)

        if show_interpret_controls:
            interpretation_group = QGroupBox(get_text("can_id_panel_interpretation"), self)
            interpretation_layout = QVBoxLayout(interpretation_group)
            interpretation_layout.addWidget(self.interpret_checkbox)
            row_layout = QHBoxLayout()
            row_layout.addWidget(self.btn_expand)
            row_layout.addWidget(self.btn_collapse)
            interpretation_layout.addLayout(row_layout)
            layout.addWidget(interpretation_group)

        can_ids_group = QGroupBox(get_text("can_id_panel_can_ids"), self)
        can_ids_layout = QVBoxLayout(can_ids_group)
        selection_layout = QHBoxLayout()
        selection_layout.addWidget(self.btn_all)
        selection_layout.addWidget(self.btn_none)
        can_ids_layout.addLayout(selection_layout)
        can_ids_layout.addWidget(self.search_box)
        can_ids_layout.addWidget(self.can_list)
        layout.addWidget(can_ids_group, 1)

        self.btn_all.clicked.connect(self._select_all)
        self.btn_none.clicked.connect(self._select_none)
        if show_interpret_controls:
            self.btn_expand.clicked.connect(self.expand_all_clicked.emit)
            self.btn_collapse.clicked.connect(self.collapse_all_clicked.emit)

        self.can_list.itemChanged.connect(self._emit_selected_ids)
        if show_interpret_controls:
            self.interpret_checkbox.toggled.connect(self.interpret_toggled.emit)
        self.search_box.textChanged.connect(self._apply_search_filter)
        if self.time_filter is not None:
            self.time_filter.range_changed.connect(self.time_range_changed.emit)

        if show_interpret_controls:
            self._interpret_vm.available_changed.connect(self.set_interpret_available)
            self._interpret_vm.enabled_changed.connect(lambda _: self.refresh_labels())

        if show_interpret_controls:
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
        ids_list = sorted(list(ids), key=can_id_sort_key)
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
                    name = self._resolve_message_name(cid)
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
                    name = self._resolve_message_name(cid)
                    if name:
                        display = f"{cid}  {name}"
                item.setText(display)

        for target_row, cid in enumerate(ids_list):
            item = self._items_by_id.get(cid)
            if item is None:
                continue
            current_row = self.can_list.row(item)
            if current_row == target_row:
                continue
            taken = self.can_list.takeItem(current_row)
            if taken is not None:
                self.can_list.insertItem(target_row, taken)

        self.can_list.setUpdatesEnabled(True)
        self.can_list.blockSignals(False)

        self._emit_selected_ids()
        self._apply_search_filter()

    def refresh_labels(self) -> None:
        if not self._current_can_ids:
            return

        interpret_enabled = self._interpret_vm.enabled

        self.can_list.setUpdatesEnabled(False)
        for cid, item in self._items_by_id.items():
            display = cid
            if interpret_enabled:
                name = self._resolve_message_name(cid)
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
        selected = self.selected_ids()
        if selected == self._last_emitted_selected_ids:
            return
        self._last_emitted_selected_ids = set(selected)
        self.selected_ids_changed.emit(selected)

    def _apply_search_filter(self, _text: str | None = None) -> None:
        needle = (self.search_box.text() or "").strip().upper()
        for index in range(self.can_list.count()):
            item = self.can_list.item(index)
            cid = str(item.data(Qt.UserRole) or "").upper()
            item.setHidden(bool(needle) and needle not in cid)
