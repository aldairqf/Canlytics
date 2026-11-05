from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, QRect
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem
from config.theme import get_active_theme


class DecodeLineLayoutDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        text = index.data(Qt.DisplayRole)
        model = index.model()
        changed = model.get_data_changed_bytes(index.row()) if hasattr(model, "get_data_changed_bytes") else set()
        if not text or ("\n" not in str(text) and not changed):
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
        # BUGS.md B-10 (same fix as DataBytesHighlightDelegate): without a clip,
        # a row that isn't quite tall enough for its decoded line count paints
        # straight into the row below instead of being cut off at the cell edge.
        painter.setClipRect(opt.rect)
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        cell_rect = opt.rect.adjusted(6, 2, -6, -2)
        lines = str(text).splitlines()
        if not lines:
            painter.restore()
            return

        line_h = max(1.0, cell_rect.height() / float(len(lines)))
        metrics = opt.fontMetrics
        text_pen = (
            opt.palette.color(QPalette.ColorRole.HighlightedText)
            if (opt.state & QStyle.State_Selected)
            else opt.palette.color(QPalette.ColorRole.Text)
        )

        for line_index, line in enumerate(lines):
            top = int(cell_rect.top() + line_index * line_h)
            bottom = int(cell_rect.top() + (line_index + 1) * line_h)
            line_rect = cell_rect.adjusted(0, top - cell_rect.top(), 0, bottom - cell_rect.bottom())
            text_y = int(
                line_rect.top()
                + max(metrics.ascent(), (line_rect.height() + metrics.ascent() - metrics.descent()) / 2.0)
            )
            if line_index == 0 and changed:
                self._draw_bytes(painter, line_rect.left() + 4, text_y, line_rect, line, changed, metrics, text_pen)
            else:
                painter.setPen(text_pen)
                painter.drawText(line_rect.left() + 4, text_y, line)

        painter.restore()

    @staticmethod
    def _draw_bytes(
        painter: QPainter,
        x: int,
        y: int,
        rect: QRect,
        text: str,
        changed: set[int],
        metrics: QFontMetrics,
        normal_color: QColor,
    ) -> None:
        theme = get_active_theme()
        byte_values = text.split()
        for byte_index, byte_value in enumerate(byte_values):
            token = byte_value + (" " if byte_index < len(byte_values) - 1 else "")
            width = metrics.horizontalAdvance(token)
            token_rect = rect.adjusted(x - rect.left(), 1, -(rect.width() - (x - rect.left()) - width), -1)
            if byte_index in changed:
                painter.fillRect(token_rect, QColor(theme.accent))
                painter.setPen(QPen(QColor(theme.accent_text)))
            else:
                painter.setPen(normal_color)
            painter.drawText(x, y, token)
            x += width
