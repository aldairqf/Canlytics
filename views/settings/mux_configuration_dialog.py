from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from config.app_config import get_text
from models.mux_config import MuxConfigEntry, parse_mux_bytes


class MuxConfigurationDialog(QDialog):
    def __init__(self, configs: list[MuxConfigEntry], parent=None):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle(get_text("mux_configuration_dialog_title"))
        self.resize(620, 360)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(
            [
                get_text("mux_configuration_can_id"),
                get_text("mux_configuration_len"),
                get_text("mux_configuration_bytes"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        self.btn_add = QPushButton(get_text("mux_configuration_add"))
        self.btn_remove = QPushButton(get_text("mux_configuration_remove"))
        self.btn_add.clicked.connect(lambda _checked=False: self._add_row())
        self.btn_remove.clicked.connect(self._remove_selected)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        controls = QHBoxLayout()
        controls.addWidget(self.btn_add)
        controls.addWidget(self.btn_remove)
        controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

        for cfg in configs:
            self._add_row(cfg)
        if self.table.rowCount() == 0:
            self._add_row()

    def configs(self) -> list[MuxConfigEntry]:
        result: list[MuxConfigEntry] = []
        for row in range(self.table.rowCount()):
            can_id = self._text(row, 0).upper()
            if not can_id:
                continue

            len_text = self._text(row, 1)
            length = None
            if len_text:
                try:
                    length = int(len_text)
                except ValueError as exc:
                    raise ValueError(f"Invalid LEN '{len_text}' for CAN ID {can_id}.") from exc

            mux_bytes = parse_mux_bytes(self._text(row, 2))
            if not mux_bytes:
                raise ValueError(f"Please set MUX bytes for CAN ID {can_id}.")

            result.append(MuxConfigEntry(can_id=can_id, length=length, mux_bytes=mux_bytes))
        return result

    def _add_row(self, config: MuxConfigEntry | None = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(config.can_id if config else ""))
        self.table.setItem(row, 1, QTableWidgetItem("" if config is None or config.length is None else str(config.length)))
        self.table.setItem(row, 2, QTableWidgetItem("" if config is None else ",".join(str(i) for i in config.mux_bytes)))

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
        if self.table.rowCount() == 0:
            self._add_row()

    def _text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return (item.text() if item else "").strip()
