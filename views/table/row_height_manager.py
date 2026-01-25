from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QStyle

from views.table.table_model import TableModel
from views.table.table_view import DataTableView
from viewmodels.table_viewmodel import TableViewModel


class RowHeightManager:
    """Helper de UI para alturas/expand/collapse sin inflar MainWindow."""

    def __init__(self, table: DataTableView, table_model: TableModel, table_vm: TableViewModel):
        self._table = table
        self._table_model = table_model
        self._table_vm = table_vm
        self._rows_have_custom_heights = False

    def expand_all(self) -> None:
        self._table_vm.set_all_expanded(True)
        self.refresh(expanded=True)

    def collapse_all(self) -> None:
        self._table_vm.set_all_expanded(False)
        self.refresh(expanded=False)

    def toggle_row(self, row: int) -> None:
        self._table_vm.toggle_row_expanded(row)
        base = self._row_base_height()
        line_count = self._table_model.get_decode_line_count(row)
        self._table.setRowHeight(row, base * (1 + max(0, line_count)))
        self._rows_have_custom_heights = True

    def refresh(self, expanded: bool | None = None) -> None:
        base_height = self._row_base_height()
        self._table.verticalHeader().setDefaultSectionSize(base_height)

        total = self._table_model.rowCount()
        chunk = 500

        if expanded is True:
            self._rows_have_custom_heights = True

            def step_expand(start: int) -> None:
                end = min(total, start + chunk)
                for row in range(start, end):
                    line_count = self._table_model.get_decode_line_count(row)
                    self._table.setRowHeight(row, base_height * (1 + max(0, line_count)))
                if end < total:
                    QTimer.singleShot(0, lambda: step_expand(end))

            step_expand(0)
            return

        if not self._rows_have_custom_heights:
            return

        def step_reset(start: int) -> None:
            end = min(total, start + chunk)
            for row in range(start, end):
                self._table.setRowHeight(row, base_height)
            if end < total:
                QTimer.singleShot(0, lambda: step_reset(end))
            else:
                self._rows_have_custom_heights = False

        step_reset(0)

    def _row_base_height(self) -> int:
        line_h = max(1, self._table.fontMetrics().lineSpacing())
        vpad = self._table.style().pixelMetric(QStyle.PM_FocusFrameVMargin, None, self._table)
        vpad = 0 if vpad < 0 else vpad
        return max(20, line_h + 2 * vpad)