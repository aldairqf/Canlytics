from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

from viewmodels.table_model import format_data_bytes


class DataBytesHighlightDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlight_bg = QColor("#2f6b3b")
        self._highlight_text = QColor("#f3fff4")

    def paint(self, painter, option, index) -> None:
        model = index.model()
        if not hasattr(model, "get_data_changed_bytes") or not hasattr(model, "get_raw_data_hex"):
            super().paint(painter, option, index)
            return

        changed_bytes = model.get_data_changed_bytes(index.row())
        text = format_data_bytes(model.get_raw_data_hex(index.row()), as_bits=bool(getattr(model, "is_data_bits_display", lambda: False)()))

        if not text:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""

        style = opt.widget.style() if opt.widget else None
        if style is None:
            super().paint(painter, option, index)
            return

        painter.save()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        text_rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget)
        if not text_rect.isValid():
            text_rect = opt.rect.adjusted(4, 0, -4, 0)

        metrics = opt.fontMetrics
        bytes_text = text.split()
        x = text_rect.left()
        y = text_rect.top() + metrics.ascent() + max(0, (text_rect.height() - metrics.height()) // 2)

        normal_pen = QPen(opt.palette.color(QPalette.ColorRole.Text))
        selected_pen = QPen(opt.palette.color(QPalette.ColorRole.HighlightedText))

        for byte_index, byte_text in enumerate(bytes_text):
            chunk = byte_text + (" " if byte_index < len(bytes_text) - 1 else "")
            width = metrics.horizontalAdvance(chunk)
            chunk_rect = text_rect.adjusted(x - text_rect.left(), 2, -(text_rect.width() - (x - text_rect.left()) - width), -2)

            if byte_index in changed_bytes:
                painter.fillRect(chunk_rect, self._highlight_bg)
                painter.setPen(self._highlight_text)
            else:
                painter.setPen(selected_pen if (opt.state & QStyle.State_Selected) else normal_pen)

            painter.drawText(x, y, chunk)
            x += width

        painter.restore()
