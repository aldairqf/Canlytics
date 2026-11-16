from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from config.app_config import get_text


class PlaybackControls(QWidget):
    def __init__(self, playback_vm, *, compact: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._vm = playback_vm
        self._disconnected = False
        self._dragging = False
        self.play_button = QPushButton(get_text("realtime_offline_play"), self)
        self.play_button.setCheckable(True)
        self.previous_button = QPushButton(get_text("realtime_offline_previous"), self)
        self.next_button = QPushButton(get_text("realtime_offline_next"), self)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 10000)
        self.slider.setMinimumWidth(100 if compact else 180)
        self._speed_buttons = []
        self.values_label = QLabel(self)
        self.values_label.setTextFormat(Qt.RichText)
        self.values_label.setVisible(not compact)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.addWidget(self.play_button)
        layout.addWidget(self.previous_button)
        if not compact:
            for label, speed in (("/4", .25), ("/2", .5), ("x1", 1.), ("x2", 2.), ("x4", 4.)):
                button = QPushButton(label, self)
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, value=speed: self._vm.set_speed(value))
                self._speed_buttons.append((button, speed))
                layout.addWidget(button)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.next_button)
        layout.addWidget(self.values_label)
        self.play_button.toggled.connect(self._vm.set_playing)
        self.previous_button.clicked.connect(lambda: self._vm.step(-1))
        self.next_button.clicked.connect(lambda: self._vm.step(1))
        self.slider.sliderPressed.connect(self._on_pressed)
        self.slider.sliderMoved.connect(self._on_moved)
        self.slider.sliderReleased.connect(self._on_released)
        self._vm.position_changed.connect(self._sync_position)
        self._vm.state_changed.connect(self._sync_state)
        self._vm.range_changed.connect(self._refresh_position)
        self._sync_state()
        self._refresh_position()

    def set_timezone(self, _mode: str) -> None:
        pass

    def set_values_html(self, html: str) -> None:
        self.values_label.setText(html)

    def clear_values(self) -> None:
        self.values_label.clear()

    def stop(self) -> None:
        self._vm.set_playing(False)

    def _on_pressed(self) -> None:
        self._dragging = True
        self._vm.set_playing(False)

    def _on_moved(self, value: int) -> None:
        low, high = self._vm.minimum, self._vm.maximum
        if low is not None and high is not None:
            self._vm.seek(low + (value / 10000) * (high - low))

    def _on_released(self) -> None:
        self._dragging = False

    def _refresh_position(self) -> None:
        self._sync_position(self._vm.position)

    def _sync_position(self, timestamp: float | None) -> None:
        low, high = self._vm.minimum, self._vm.maximum
        if timestamp is None or self._dragging or low is None or high is None:
            return
        span = high - low
        value = round(10000 * (timestamp - low) / span) if span > 0 else 0
        self.slider.blockSignals(True)
        self.slider.setValue(max(0, min(10000, value)))
        self.slider.blockSignals(False)

    def _sync_state(self) -> None:
        self.play_button.blockSignals(True)
        self.play_button.setChecked(self._vm.playing)
        self.play_button.setText(get_text("realtime_offline_pause" if self._vm.playing else "realtime_offline_play"))
        self.play_button.blockSignals(False)
        for button, speed in self._speed_buttons:
            button.blockSignals(True)
            button.setChecked(self._vm.speed == speed)
            button.blockSignals(False)

    def closeEvent(self, event) -> None:
        self.stop()
        if self._disconnected:
            super().closeEvent(event)
            return
        self._disconnected = True
        for signal, slot in ((self._vm.position_changed, self._sync_position), (self._vm.state_changed, self._sync_state), (self._vm.range_changed, self._refresh_position)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)
