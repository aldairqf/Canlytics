from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal as QtSignal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsSceneMouseEvent,
    QMenu,
    QStyleOptionGraphicsItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from models.bit_track import BitTrack


class _BitTrackItem(pg.GraphicsObject):
    def __init__(
        self,
        lane: int,
        color: QColor,
        timestamps: list[float],
        states: list[int],
        latest_timestamp: float | None,
        time_transform: Callable[[float], float],
    ) -> None:
        super().__init__()
        self._lane = lane
        self._color = QColor(color)
        self._raw_timestamps = list(timestamps)
        self._states = list(states)
        self._time_transform = time_transform
        self._timestamps = [time_transform(value) for value in timestamps]
        self._latest_timestamp = self._transform_optional(latest_timestamp)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        self.setZValue(1)

    def set_lane(self, lane: int, color: QColor) -> None:
        if lane == self._lane and color == self._color:
            return
        self.prepareGeometryChange()
        self._lane = lane
        self._color = QColor(color)
        self.update()

    def set_data(self, timestamps: list[float], states: list[int], latest_timestamp: float | None) -> None:
        self.prepareGeometryChange()
        self._raw_timestamps = list(timestamps)
        self._states = list(states)
        self._timestamps = [self._time_transform(value) for value in timestamps]
        self._latest_timestamp = self._transform_optional(latest_timestamp)
        self.update()

    def append_transitions(self, transitions: list[tuple[float, int]]) -> None:
        if not transitions:
            return
        start = self._timestamps[-1] if self._timestamps else self._time_transform(transitions[0][0])
        self.prepareGeometryChange()
        for timestamp, state in transitions:
            self._raw_timestamps.append(timestamp)
            self._timestamps.append(self._time_transform(timestamp))
            self._states.append(state)
        latest_transition = self._timestamps[-1]
        if self._latest_timestamp is None or latest_transition > self._latest_timestamp:
            self._latest_timestamp = latest_transition
        self.update(self._update_rect(start))

    def set_latest_timestamp(self, timestamp: float | None) -> None:
        value = self._transform_optional(timestamp)
        if value == self._latest_timestamp:
            return
        start = self._timestamps[-1] if self._timestamps else value
        self.prepareGeometryChange()
        self._latest_timestamp = value
        self.update(self._update_rect(start))

    def set_time_transform(self, transform: Callable[[float], float]) -> None:
        self.prepareGeometryChange()
        self._time_transform = transform
        self._timestamps = [transform(value) for value in self._raw_timestamps]
        self.update()

    def boundingRect(self) -> QRectF:
        if not self._timestamps:
            return QRectF(0.0, self._lane * 3.0, 1e-9, 1.8)
        right = self._latest_timestamp
        if right is None or right <= self._timestamps[-1]:
            right = self._timestamps[-1] + 1e-9
        return QRectF(self._timestamps[0], self._lane * 3.0, right - self._timestamps[0], 1.8)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        if not self._timestamps:
            return
        left = option.exposedRect.left()
        right = option.exposedRect.right()
        start_index = max(0, bisect_right(self._timestamps, left) - 1)
        end_index = min(len(self._timestamps), bisect_left(self._timestamps, right) + 1)
        top = self._lane * 3.0 + 0.2
        low_color = QColor(self._color)
        low_color.setAlpha(70)
        high_color = QColor(self._color)
        high_color.setAlpha(210)
        painter.save()
        painter.setClipRect(option.exposedRect, Qt.ClipOperation.IntersectClip)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(start_index, end_index):
            start = self._timestamps[index]
            end = self._timestamps[index + 1] if index + 1 < len(self._timestamps) else self._latest_timestamp
            if end is None or end <= start:
                continue
            x0 = max(left, start)
            x1 = min(right, end)
            if x1 <= x0:
                continue
            color = high_color if self._states[index] else low_color
            painter.fillRect(QRectF(x0, top, x1 - x0, 1.4), color)
        painter.restore()

    def _transform_optional(self, timestamp: float | None) -> float | None:
        return self._time_transform(timestamp) if timestamp is not None else None

    def _update_rect(self, start: float | None) -> QRectF:
        if start is None:
            start = self._timestamps[-1] if self._timestamps else 0.0
        end = self._latest_timestamp
        if end is None or end <= start:
            end = start + 1e-9
        return QRectF(start, self._lane * 3.0, end - start, 1.8)


class StateTrackerWidget(QWidget):
    track_remove_requested = QtSignal(object)

    def __init__(self, primary_plot: pg.PlotWidget, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plot = pg.PlotWidget(self)
        self.plot.setMaximumHeight(180)
        self.plot.setMinimumHeight(80)
        self.plot.setXLink(primary_plot)
        self.plot.setMenuEnabled(False)
        self.plot.getViewBox().setMenuEnabled(False)
        self.plot.hideAxis("bottom")
        self.plot.setLabel("left", get_text("state_tracker_axis"))
        self._cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#f0b429", width=1))
        self.plot.addItem(self._cursor)
        self._tracks: tuple[BitTrack, ...] = ()
        self._items: dict[BitTrack, _BitTrackItem] = {}
        self._data: dict[BitTrack, tuple[list[float], list[int]]] = {}
        self._latest_timestamp: float | None = None
        self._time_transform: Callable[[float], float] = float
        self._cursor_callback: Callable[[float], None] | None = None
        self.plot.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)
        self.setVisible(False)

    def set_cursor_callback(self, callback: Callable[[float], None]) -> None:
        self._cursor_callback = callback

    def set_tracks(self, tracks: tuple[BitTrack, ...]) -> None:
        self._tracks = tracks
        for item in self._items.values():
            self.plot.removeItem(item)
        self._items.clear()
        self._data = {track: self._data.get(track, ([], [])) for track in tracks}
        self._render_tracks()
        self.setVisible(bool(tracks))

    def set_track_data(self, track: BitTrack, data: tuple[list[float], list[int]]) -> None:
        self._data[track] = data
        item = self._items.get(track)
        if item is not None:
            item.set_data(*data, self._latest_timestamp)

    def append_transitions(self, changes: dict[BitTrack, list[tuple[float, int]]]) -> None:
        for track, transitions in changes.items():
            timestamps, states = self._data.setdefault(track, ([], []))
            timestamps.extend(timestamp for timestamp, _ in transitions)
            states.extend(state for _, state in transitions)
            item = self._items.get(track)
            if item is not None:
                item.append_transitions(transitions)

    def set_latest_timestamp(self, timestamp: float | None) -> None:
        self._latest_timestamp = timestamp
        for item in self._items.values():
            item.set_latest_timestamp(timestamp)

    def set_time_transform(self, transform: Callable[[float], float]) -> None:
        self._time_transform = transform
        for item in self._items.values():
            item.set_time_transform(transform)
            item.set_latest_timestamp(self._latest_timestamp)

    def set_cursor(self, timestamp: float) -> None:
        self._cursor.setPos(timestamp)

    def apply_style(self, background: str, foreground: str) -> None:
        self.plot.setBackground(background)
        for name in ("left", "bottom", "right", "top"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(foreground))
            axis.setTextPen(pg.mkPen(foreground))
        self.plot.setLabel("left", get_text("state_tracker_axis"), color=foreground)

    def _render_tracks(self) -> None:
        for index, track in enumerate(self._tracks):
            timestamps, states = self._data.get(track, ([], []))
            color = pg.intColor(index, hues=max(1, len(self._tracks)))
            item = _BitTrackItem(
                index,
                color,
                timestamps,
                states,
                self._latest_timestamp,
                self._time_transform,
            )
            self._items[track] = item
            self.plot.addItem(item)
        self.plot.getAxis("left").setTicks([[(index * 3 + 0.9, track.label) for index, track in enumerate(self._tracks)]])
        if self._tracks:
            self.plot.setYRange(-0.1, len(self._tracks) * 3 - 1.0, padding=0)

    def _on_mouse_clicked(self, event: QGraphicsSceneMouseEvent) -> None:
        if not self.plot.getViewBox().sceneBoundingRect().contains(event.scenePos()):
            return
        point = self.plot.getViewBox().mapSceneToView(event.scenePos())
        if event.button() == Qt.MouseButton.LeftButton and self._cursor_callback is not None:
            self._cursor_callback(float(point.x()))
        elif event.button() == Qt.MouseButton.RightButton:
            index = int(point.y() // 3)
            if 0 <= index < len(self._tracks):
                track = self._tracks[index]
                menu = QMenu(self)
                remove = menu.addAction(get_text("state_tracker_remove_lane").format(track=track.label))
                if menu.exec(event.screenPos()) is remove:
                    self.track_remove_requested.emit(track)
