from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout

from viewmodels.dbc_manager_viewmodel import DbcManagerViewModel
from viewmodels.interpretation_viewmodel import InterpretationViewModel
from viewmodels.table_model import TableModel
from views.table.table_view import DataTableView
from views.table.trace_filter_bar import TraceFilterBar
from views.widgets.can_id_panel import CanIdPanelWidget


class MainWindowView(QWidget):

    def __init__(
        self,
        table_model: TableModel,
        *,
        dbc_manager: DbcManagerViewModel,
        interpret_vm: InterpretationViewModel,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.panel = CanIdPanelWidget(
            dbc_manager.resolve_message_name,
            interpret_vm,
            parent=self,
        )
        self.table = DataTableView(table_model)
        self.trace_filter_bar = TraceFilterBar(self)
        table_panel = QWidget(self)
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.trace_filter_bar)
        table_layout.addWidget(self.table, 1)

        layout = QHBoxLayout(self)
        layout.addWidget(table_panel, 4)
        layout.addWidget(self.panel, 1)
