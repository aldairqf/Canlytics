from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Signal as QtSignal, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from models.hmi_video_models import HmiFrameView, HmiRoi


class HmiFrameEditorWidget(QWidget):
    roi_drawn = QtSignal(int, int, int, int)
    anchor_drawn = QtSignal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 360)
        self.setMouseTracking(True)
        self._pixmap: QPixmap | None = None
        self._frame_size = (1, 1)
        self._rois: list[HmiRoi] = []
        self._selected_roi_id: str | None = None
        self._draw_mode = ""
        self._drag_start: QPoint | None = None
        self._drag_end: QPoint | None = None
        self._image_rect = QRect()

    def set_frame(self, frame: HmiFrameView | None) -> None:
        if frame is None:
            self._pixmap = None
            self._frame_size = (1, 1)
            self.update()
            return

        image = QImage(
            frame.image_bytes,
            frame.width,
            frame.height,
            frame.bytes_per_line,
            QImage.Format_RGB888,
        ).copy()
        self._pixmap = QPixmap.fromImage(image)
        self._frame_size = (max(1, frame.width), max(1, frame.height))
        self.update()

    def set_rois(self, rois: list[HmiRoi], selected_roi_id: str | None = None) -> None:
        self._rois = list(rois)
        self._selected_roi_id = selected_roi_id
        self.update()

    def set_draw_mode(self, mode: str | bool) -> None:
        if isinstance(mode, bool):
            self._draw_mode = "roi" if mode else ""
        else:
            self._draw_mode = (mode or "").strip()
        if not self._draw_mode:
            self._drag_start = None
            self._drag_end = None
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202020"))
        if self._pixmap is None:
            painter.setPen(QColor("#bbbbbb"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Load a video to start")
            return

        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        self._image_rect = QRect(x, y, scaled.width(), scaled.height())
        painter.drawPixmap(self._image_rect.topLeft(), scaled)

        for roi in self._rois:
            rect = self._roi_to_widget_rect(roi)
            if roi.has_anchor:
                anchor_rect = self._anchor_to_widget_rect(roi)
                painter.setPen(QPen(QColor("#ffcc33"), 2, Qt.DashLine))
                painter.drawRect(anchor_rect)
            pen = QPen(QColor(roi.color), 3 if roi.roi_id == self._selected_roi_id else 2)
            painter.setPen(pen)
            painter.drawRect(rect)
            label_rect = self._label_rect(rect, roi.name)
            painter.fillRect(label_rect, QColor(0, 0, 0, 160))
            painter.drawText(label_rect.adjusted(4, 0, -4, 0), Qt.AlignLeft | Qt.AlignVCenter, roi.name)

        if self._draw_mode and self._drag_start and self._drag_end:
            color = "#ffcc33" if self._draw_mode == "anchor" else "#ffffff"
            painter.setPen(QPen(QColor(color), 2, Qt.DashLine))
            painter.drawRect(QRect(self._drag_start, self._drag_end).normalized())

    def mousePressEvent(self, event) -> None:
        if not self._draw_mode or event.button() != Qt.LeftButton:
            return
        if not self._image_rect.contains(event.position().toPoint()):
            return
        self._drag_start = event.position().toPoint()
        self._drag_end = self._drag_start
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if not self._draw_mode or self._drag_start is None:
            return
        self._drag_end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if not self._draw_mode or self._drag_start is None or self._drag_end is None:
            return
        if event.button() != Qt.LeftButton:
            return
        widget_rect = QRect(self._drag_start, self._drag_end).normalized()
        self._drag_start = None
        self._drag_end = None
        self.update()
        roi_rect = self._widget_rect_to_roi_rect(widget_rect)
        if roi_rect.width() <= 3 or roi_rect.height() <= 3:
            return
        if self._draw_mode == "anchor":
            self.anchor_drawn.emit(roi_rect.x(), roi_rect.y(), roi_rect.width(), roi_rect.height())
        else:
            self.roi_drawn.emit(roi_rect.x(), roi_rect.y(), roi_rect.width(), roi_rect.height())

    def _roi_to_widget_rect(self, roi: HmiRoi) -> QRect:
        fx = self._image_rect.width() / max(1, self._frame_size[0])
        fy = self._image_rect.height() / max(1, self._frame_size[1])
        return QRect(
            int(self._image_rect.x() + roi.x * fx),
            int(self._image_rect.y() + roi.y * fy),
            max(1, int(roi.width * fx)),
            max(1, int(roi.height * fy)),
        )

    def _anchor_to_widget_rect(self, roi: HmiRoi) -> QRect:
        fx = self._image_rect.width() / max(1, self._frame_size[0])
        fy = self._image_rect.height() / max(1, self._frame_size[1])
        return QRect(
            int(self._image_rect.x() + int(roi.anchor_x or 0) * fx),
            int(self._image_rect.y() + int(roi.anchor_y or 0) * fy),
            max(1, int(int(roi.anchor_width or 1) * fx)),
            max(1, int(int(roi.anchor_height or 1) * fy)),
        )

    def _label_rect(self, rect: QRect, label: str) -> QRect:
        width = min(max(80, len(label) * 8), 140)
        height = 18

        top_rect = QRect(rect.x(), rect.y() - height - 2, width, height)
        if top_rect.y() >= self._image_rect.y():
            return top_rect

        right_rect = QRect(rect.right() + 4, rect.y(), width, height)
        if right_rect.right() <= self._image_rect.right():
            return right_rect

        left_rect = QRect(rect.x() - width - 4, rect.y(), width, height)
        if left_rect.x() >= self._image_rect.x():
            return left_rect

        bottom_rect = QRect(rect.x(), rect.bottom() + 4, width, height)
        if bottom_rect.bottom() <= self._image_rect.bottom():
            return bottom_rect

        return QRect(rect.x(), max(self._image_rect.y(), rect.y() - height - 2), width, height)

    def _widget_rect_to_roi_rect(self, rect: QRect) -> QRect:
        clipped = rect.intersected(self._image_rect)
        fx = max(1e-9, self._frame_size[0] / max(1, self._image_rect.width()))
        fy = max(1e-9, self._frame_size[1] / max(1, self._image_rect.height()))
        return QRect(
            int((clipped.x() - self._image_rect.x()) * fx),
            int((clipped.y() - self._image_rect.y()) * fy),
            max(1, int(clipped.width() * fx)),
            max(1, int(clipped.height() * fy)),
        )
