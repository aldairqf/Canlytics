from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout

from services.dbc_manager import DbcManager
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.table_model import TableModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from views.table.table_view import DataTableView
from views.widgets.can_id_panel import CanIdPanelWidget


class MainWindowView(QWidget):

    def __init__(
        self,
        table_model: TableModel,
        *,
        dbc_manager: DbcManager,
        interpret_vm: InterpretationViewModel,
        time_config_vm: TimeConfigViewModel,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.panel = CanIdPanelWidget(dbc_manager, interpret_vm, time_config_vm, parent=self)
        self.table = DataTableView(table_model)

        layout = QHBoxLayout(self)
        layout.addWidget(self.table, 4)
        layout.addWidget(self.panel, 1)
