from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem


class DecodeLineLayoutDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        text = index.data(Qt.DisplayRole)
        if not text or "\n" not in str(text):
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
            painter.setPen(text_pen)
            text_y = int(
                line_rect.top()
                + max(metrics.ascent(), (line_rect.height() + metrics.ascent() - metrics.descent()) / 2.0)
            )
            painter.drawText(line_rect.left() + 4, text_y, line)

        painter.restore()
