from PySide6.QtWidgets import QTableView, QAbstractItemView, QStyleOptionViewItem, QStyle
from PySide6.QtCore import Signal, Qt


class DataTableView(QTableView):
    decode_context_requested = Signal(int, int, object)
    row_toggle_requested = Signal(int)

    def __init__(self, model):
        super().__init__()
        self.setModel(model)

        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)

        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsClickable(True)
        self._apply_column_visibility()

    def _apply_column_visibility(self):
        model = self.model()
        if not model or not hasattr(model, "_columns"):
            return
        hidden = {"B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7"}
        for name in hidden:
            if name in model._columns:
                self.setColumnHidden(model._columns.index(name), True)

    def _decode_hit_at_pos(self, pos):
        index = self.indexAt(pos)
        if not index.isValid():
            return None

        model = self.model()
        if not hasattr(model, "_columns") or "DATA" not in model._columns:
            return None
        if model._columns[index.column()] != "DATA":
            return None

        if (
            hasattr(model, "is_decode_enabled")
            and not model.is_decode_enabled()
        ) or (
            hasattr(model, "is_row_expanded")
            and not model.is_row_expanded(index.row())
        ):
            return None

        if not hasattr(model, "get_decode_line_count"):
            return None

        decode_count = int(model.get_decode_line_count(index.row()) or 0)
        if decode_count <= 0:
            return None

        data_col = model._columns.index("DATA")
        data_index = model.index(index.row(), data_col)
        if not data_index.isValid():
            return None

        opt = QStyleOptionViewItem()
        opt.initFrom(self.viewport())
        opt.rect = self.visualRect(data_index)
        opt.state |= QStyle.State_Active
        opt.font = self.font()

        text_rect = self.style().subElementRect(QStyle.SE_ItemViewItemText, opt, self.viewport())
        if not text_rect.isValid():
            text_rect = opt.rect

        y = pos.y() - text_rect.top()
        if y < 0:
            return None

        line_h = max(1, self.fontMetrics().lineSpacing())
        total_lines = 1 + decode_count
        text_h = total_lines * line_h

        extra = text_rect.height() - text_h
        if extra < 0:
            extra = 0

        align = opt.displayAlignment & Qt.AlignVertical_Mask
        if align == Qt.AlignVCenter:
            offset = extra / 2.0
        elif align == Qt.AlignBottom:
            offset = float(extra)
        else:
            offset = 0.0

        y_in_text = y - offset
        if y_in_text < 0 or y_in_text >= text_h:
            return None

        visual_line = int(y_in_text // line_h)
        if visual_line <= 0:
            return None

        decode_line_index = visual_line - 1
        if decode_line_index < 0 or decode_line_index >= decode_count:
            return None

        return index.row(), decode_line_index, self.viewport().mapToGlobal(pos)

    def contextMenuEvent(self, event):
        hit = self._decode_hit_at_pos(event.pos())
        if hit is None:
            return super().contextMenuEvent(event)
        row, line_index, global_pos = hit
        self.selectRow(row)
        self.decode_context_requested.emit(row, line_index, global_pos)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                model = self.model()
                if hasattr(model, "_columns") and "DATA" in model._columns:
                    if model._columns[index.column()] == "DATA":
                        if hasattr(model, "is_decode_enabled") and model.is_decode_enabled():
                            self.row_toggle_requested.emit(index.row())
                            event.accept()
                            return
        super().mouseDoubleClickEvent(event)
