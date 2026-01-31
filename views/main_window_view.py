from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout

from services.contracts import DbcService
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.table_model import TableModel
from views.table.table_view import DataTableView
from views.widgets.can_id_panel import CanIdPanelWidget


class MainWindowView(QWidget):

    def __init__(
        self,
        table_model: TableModel,
        *,
        dbc_manager: DbcService,
        interpret_vm: InterpretationViewModel,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.panel = CanIdPanelWidget(dbc_manager, interpret_vm, parent=self)
        self.table = DataTableView(table_model)

        layout = QHBoxLayout(self)
        layout.addWidget(self.table, 4)
        layout.addWidget(self.panel, 1)
