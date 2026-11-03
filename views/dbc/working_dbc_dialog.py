from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from cantools.database.can import Message, Signal

if TYPE_CHECKING:
    from viewmodels.main_window_viewmodel import MainWindowViewModel


class _MessageEditor(QDialog):
    def __init__(self, parent: QWidget, message: Message | None = None):
        super().__init__(parent)
        self.setWindowTitle(get_text("working_dbc_message_editor"))
        form = QFormLayout(self)
        self.name = QLineEdit(message.name if message else "")
        self.frame_id = QLineEdit(f"{message.frame_id:X}" if message else "")
        self.length = QSpinBox()
        self.length.setRange(0, 8)
        self.length.setValue(message.length if message else 8)
        self.extended = QCheckBox()
        self.extended.setChecked(message.is_extended_frame if message else False)
        self.comment = QLineEdit(message.comment or "" if message else "")
        form.addRow(get_text("working_dbc_name"), self.name)
        form.addRow(get_text("working_dbc_can_id_hex"), self.frame_id)
        form.addRow(get_text("working_dbc_length"), self.length)
        form.addRow(get_text("working_dbc_extended_frame"), self.extended)
        form.addRow(get_text("working_dbc_comment"), self.comment)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class _SignalEditor(QDialog):
    def __init__(self, parent: QWidget, signal: Signal | None = None):
        super().__init__(parent)
        self.setWindowTitle(get_text("working_dbc_signal_editor"))
        form = QFormLayout(self)
        self.name = QLineEdit(signal.name if signal else "")
        self.start = QSpinBox()
        self.start.setRange(0, 63)
        self.start.setValue(signal.start if signal else 0)
        self.length = QSpinBox()
        self.length.setRange(1, 64)
        self.length.setValue(signal.length if signal else 1)
        self.byte_order = QComboBox()
        self.byte_order.addItem(get_text("working_dbc_little_endian"), "little_endian")
        self.byte_order.addItem(get_text("working_dbc_big_endian"), "big_endian")
        if signal:
            self.byte_order.setCurrentIndex(self.byte_order.findData(signal.byte_order))
        self.signed = QCheckBox()
        self.signed.setChecked(signal.is_signed if signal else False)
        self.floating = QCheckBox()
        self.floating.setChecked(signal.is_float if signal else False)
        self.scale = QLineEdit(repr(signal.scale) if signal else "1.0")
        self.offset = QLineEdit(repr(signal.offset) if signal else "0.0")
        self.minimum = QLineEdit("" if signal is None or signal.minimum is None else str(signal.minimum))
        self.maximum = QLineEdit("" if signal is None or signal.maximum is None else str(signal.maximum))
        self.unit = QLineEdit(signal.unit or "" if signal else "")
        self.comment = QLineEdit(signal.comment or "" if signal else "")
        for label, widget in (
            ("working_dbc_name", self.name), ("working_dbc_start_bit", self.start),
            ("working_dbc_signal_length", self.length), ("working_dbc_byte_order", self.byte_order),
            ("working_dbc_signed", self.signed), ("working_dbc_float", self.floating),
            ("working_dbc_scale", self.scale),
            ("working_dbc_offset", self.offset), ("working_dbc_minimum", self.minimum),
            ("working_dbc_maximum", self.maximum), ("working_dbc_unit", self.unit),
            ("working_dbc_comment", self.comment),
        ):
            form.addRow(get_text(label), widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, object]:
        return {
            "start": self.start.value(), "length": self.length.value(),
            "byte_order": self.byte_order.currentData(), "is_signed": self.signed.isChecked(),
            "is_float": self.floating.isChecked(),
            "scale": float(self.scale.text()), "offset": float(self.offset.text()),
            "minimum": float(self.minimum.text()) if self.minimum.text().strip() else None,
            "maximum": float(self.maximum.text()) if self.maximum.text().strip() else None,
            "unit": self.unit.text().strip() or None,
            "comment": self.comment.text().strip() or None,
        }


class WorkingDbcDialog(QDialog):
    """Manage and export the editable DBC through the main-window ViewModel."""

    def __init__(self, viewmodel: MainWindowViewModel, parent: QWidget | None = None):
        super().__init__(parent)
        self.viewmodel = viewmodel
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("working_dbc_title"))
        self.resize(760, 520)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            get_text("working_dbc_name"), get_text("working_dbc_can_id_hex"),
            get_text("working_dbc_geometry"), get_text("working_dbc_details"),
        ])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 110)
        self.tree.setColumnWidth(2, 100)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit_selected())
        self.status = QLabel()
        self.status.setWordWrap(True)
        controls = QHBoxLayout()
        self.add_message_button = QPushButton(get_text("working_dbc_add_message"))
        self.add_signal_button = QPushButton(get_text("working_dbc_add_signal"))
        self.edit_button = QPushButton(get_text("working_dbc_edit"))
        self.delete_button = QPushButton(get_text("working_dbc_delete"))
        self.export_button = QPushButton(get_text("working_dbc_export"))
        for button in (self.add_message_button, self.add_signal_button, self.edit_button,
                       self.delete_button, self.export_button):
            controls.addWidget(button)
        controls.addStretch()
        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        layout.addWidget(close_buttons)
        self.add_message_button.clicked.connect(self._add_message)
        self.add_signal_button.clicked.connect(self._add_signal)
        self.edit_button.clicked.connect(self._edit_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.export_button.clicked.connect(self._export)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self._refresh()

    def _selected_message(self) -> tuple[int, str | None] | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        if item.parent() is not None:
            return int(item.parent().data(0, Qt.ItemDataRole.UserRole)), item.data(0, Qt.ItemDataRole.UserRole)
        return int(item.data(0, Qt.ItemDataRole.UserRole)), None

    def _update_buttons(self) -> None:
        selected = self._selected_message()
        self.add_signal_button.setEnabled(selected is not None and selected[1] is None)
        self.edit_button.setEnabled(selected is not None)
        self.delete_button.setEnabled(selected is not None)

    def _refresh(self, selected_frame: int | None = None) -> None:
        self.tree.clear()
        for message in self.viewmodel.list_working_messages():
            row = QTreeWidgetItem([
                message.name, f"{message.frame_id:X}",
                get_text("working_dbc_bytes").format(length=message.length), message.comment or "",
            ])
            row.setData(0, Qt.ItemDataRole.UserRole, message.frame_id)
            self.tree.addTopLevelItem(row)
            for signal in message.signals:
                details = get_text("working_dbc_signal_details").format(
                    byte_order=get_text("working_dbc_little_endian" if signal.byte_order == "little_endian" else "working_dbc_big_endian"),
                    signed=get_text("working_dbc_signed_yes" if signal.is_signed else "working_dbc_signed_no"),
                    scale=repr(signal.scale), offset=repr(signal.offset), unit=signal.unit or "",
                    minimum="" if signal.minimum is None else f"min {signal.minimum:g}",
                    maximum="" if signal.maximum is None else f"max {signal.maximum:g}",
                    comment=signal.comment or "",
                )
                child = QTreeWidgetItem([
                    signal.name, "", f"{signal.start} / {signal.length}", details,
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, signal.name)
                child.setToolTip(3, details)
                row.addChild(child)
            row.setExpanded(True)
            if message.frame_id == selected_frame:
                self.tree.setCurrentItem(row)
        self._update_buttons()
        if not self.tree.topLevelItemCount() and not self.status.text().startswith((
            get_text("working_dbc_saved_prefix").split("{path}")[0],
            get_text("working_dbc_exported_prefix").split("{path}")[0],
        )):
            self.status.setText(get_text("working_dbc_empty"))
        elif self.tree.topLevelItemCount() and self.status.text() == get_text("working_dbc_empty"):
            self.status.clear()

    def _run_edit(self, operation: Callable[[], Path]) -> None:
        try:
            path = operation()
        except Exception as exc:
            QMessageBox.warning(self, get_text("working_dbc_error_title"), str(exc))
            return
        self.status.setText(get_text("working_dbc_saved_prefix").format(path=path))
        selected = self._selected_message()
        self._refresh(selected[0] if selected else None)

    def _add_message(self) -> None:
        editor = _MessageEditor(self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            frame_id = int(editor.frame_id.text().strip().removeprefix("0x").removeprefix("0X"), 16)
        except ValueError:
            QMessageBox.warning(self, get_text("working_dbc_error_title"), get_text("working_dbc_invalid_id"))
            return
        self._run_edit(lambda: self.viewmodel.add_working_message(
            editor.name.text().strip(), frame_id, editor.length.value(), editor.extended.isChecked(),
        ))

    def _add_signal(self) -> None:
        selected = self._selected_message()
        if selected is None or selected[1] is not None:
            return
        editor = _SignalEditor(self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        self._run_edit(lambda: self.viewmodel.add_working_signal(
            selected[0], editor.name.text().strip(), **editor.values(),
        ))

    def _edit_selected(self) -> None:
        selected = self._selected_message()
        if selected is None:
            return
        frame_id, signal_name = selected
        message = next(item for item in self.viewmodel.list_working_messages() if item.frame_id == frame_id)
        if signal_name is None:
            editor = _MessageEditor(self, message)
            if editor.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                new_id = int(editor.frame_id.text().strip().removeprefix("0x").removeprefix("0X"), 16)
            except ValueError:
                QMessageBox.warning(self, get_text("working_dbc_error_title"), get_text("working_dbc_invalid_id"))
                return
            self._run_edit(lambda: self.viewmodel.edit_working_message(
                frame_id, name=editor.name.text().strip(), new_frame_id=new_id,
                length=editor.length.value(), comment=editor.comment.text(),
                is_extended_frame=editor.extended.isChecked(),
            ))
        else:
            signal = message.get_signal_by_name(signal_name)
            editor = _SignalEditor(self, signal)
            if editor.exec() != QDialog.DialogCode.Accepted:
                return
            self._run_edit(lambda: self.viewmodel.edit_working_signal(
                frame_id, signal_name, new_name=editor.name.text().strip(), **editor.values(),
            ))

    def _delete_selected(self) -> None:
        selected = self._selected_message()
        if selected is None:
            return
        frame_id, signal_name = selected
        answer = QMessageBox.question(
            self, get_text("working_dbc_delete_title"), get_text("working_dbc_delete_message"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if signal_name is None:
            operation = lambda: self.viewmodel.delete_working_message(frame_id)
        else:
            operation = lambda: self.viewmodel.delete_working_signal(frame_id, signal_name)
        self._run_edit(operation)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, get_text("working_dbc_export_title"), "working.dbc", get_text("working_dbc_file_filter"),
        )
        if not path:
            return
        if Path(path).suffix.lower() != ".dbc":
            path = f"{path}.dbc"
        try:
            output = self.viewmodel.export_working_dbc(path)
        except Exception as exc:
            QMessageBox.warning(self, get_text("working_dbc_error_title"), str(exc))
            return
        self.status.setText(get_text("working_dbc_exported_prefix").format(path=output))
