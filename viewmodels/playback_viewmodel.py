from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from config.defaults import PLAYBACK_SPEEDS, PLAYBACK_TICK_MS


class PlaybackViewModel(QObject):
    state_changed = Signal()
    position_changed = Signal(float)
    range_changed = Signal()

    def __init__(self, cursor_vm, parent: QObject | None = None):
        super().__init__(parent)
        self._cursor_vm = cursor_vm
        self._playing = False
        self._speed = 1.0
        self._position = cursor_vm.timestamp
        self._minimum: float | None = None
        self._maximum: float | None = None
        self._step_size = PLAYBACK_TICK_MS / 1000.0
        self._step_handler = None
        self._timer = QTimer(self)
        self._timer.setInterval(PLAYBACK_TICK_MS)
        self._timer.timeout.connect(lambda: self.step(1, timed=True))
        cursor_vm.cursor_changed.connect(self._on_cursor_changed)

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def position(self) -> float | None:
        return self._position

    @property
    def minimum(self) -> float | None:
        return self._minimum

    @property
    def maximum(self) -> float | None:
        return self._maximum

    def set_playing(self, playing: bool) -> None:
        playing = bool(playing)
        if self._playing == playing:
            return
        self._playing = playing
        if playing:
            if self._maximum is not None and self._position is not None and self._position >= self._maximum:
                self.seek(self._minimum if self._minimum is not None else self._position)
            self._timer.start()
        else:
            self._timer.stop()
        self.state_changed.emit()

    def set_speed(self, speed: float) -> None:
        speed = min(PLAYBACK_SPEEDS, key=lambda item: abs(item - float(speed)))
        if speed != self._speed:
            self._speed = speed
            self.state_changed.emit()

    def set_range(self, minimum: float, maximum: float) -> None:
        """Set the loaded data's time range (global epoch domain); only the composition root calls this."""
        self._minimum, self._maximum = float(minimum), float(maximum)
        self.range_changed.emit()
        if self._position is None:
            self.seek(self._minimum)

    def clear_range(self) -> None:
        self._minimum = self._maximum = None
        self.set_playing(False)
        self.range_changed.emit()

    def set_step_handler(self, handler) -> None:
        self._step_handler = handler

    def seek(self, timestamp: float) -> None:
        self._position = float(timestamp)
        self._cursor_vm.set_timestamp(self._position, "playback")
        self.position_changed.emit(self._position)

    def step(self, direction: int, *, timed: bool = False) -> None:
        if self._step_handler is not None and not timed:
            self._step_handler(1 if direction >= 0 else -1)
            return
        if self._position is None:
            if self._minimum is None:
                return
            self.seek(self._minimum)
            return
        size = self._step_size * (self._speed if timed else 1.0)
        value = self._position + (1 if direction >= 0 else -1) * size
        if self._minimum is not None:
            value = max(self._minimum, value)
        if self._maximum is not None:
            value = min(self._maximum, value)
        self.seek(value)
        if timed and self._maximum is not None and value >= self._maximum:
            self.set_playing(False)

    def shutdown(self) -> None:
        self.set_playing(False)
        self._step_handler = None

    def _on_cursor_changed(self, timestamp: float, _source: str) -> None:
        self._position = float(timestamp)
        self.position_changed.emit(self._position)
