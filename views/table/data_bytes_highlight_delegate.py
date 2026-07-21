from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

from config.theme import get_active_theme
from services.signal_formatting import format_data_bytes


class DataBytesHighlightDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

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
        # BUGS.md B-10: bits-mode text (~64 chars) is ~3x hex's width and would
        # otherwise overpaint neighboring cells when the column is sized for hex.
        painter.setClipRect(opt.rect)
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
                # Same "this changed" token Diff Analyzer/Matrix use (theme.accent) --
                # was QPalette.Highlight, coincidentally the same hex but via a
                # separate, re-themeable-independently path.
                theme = get_active_theme()
                painter.fillRect(chunk_rect, QColor(theme.accent))
                painter.setPen(QPen(QColor(theme.accent_text)))
            else:
                painter.setPen(selected_pen if (opt.state & QStyle.State_Selected) else normal_pen)

            painter.drawText(x, y, chunk)
            x += width

        painter.restore()
