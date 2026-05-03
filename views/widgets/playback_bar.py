from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal as QtSignal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSlider, QWidget

_SPEEDS: list[tuple[str, float]] = [
    ("/4", 0.25),
    ("/2", 0.50),
    ("x1", 1.00),
    ("x2", 2.00),
    ("x4", 4.00),
]
_TICK_MS = 50   # 20 fps


class PlaybackBar(QWidget):
    time_changed = QtSignal(float)
    playback_started = QtSignal()
    playback_paused = QtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._t_min = 0.0
        self._t_max = 1.0
        self._current = 0.0
        self._playing = False
        self._speed = 1.0
        self._dragging = False
        self._tz_mode: str = "none"

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

        self._btn_play = QPushButton("▶", self)
        self._btn_play.setFixedWidth(34)
        self._btn_play.clicked.connect(self._toggle_play)

        self._speed_btns: list[QPushButton] = []
        speed_row = QHBoxLayout()
        speed_row.setSpacing(2)
        speed_row.setContentsMargins(0, 0, 0, 0)
        for i, (label, _) in enumerate(_SPEEDS):
            btn = QPushButton(label, self)
            btn.setFixedWidth(34)
            btn.setCheckable(True)
            btn.setChecked(i == 2)
            btn.clicked.connect(lambda _, idx=i: self._set_speed_index(idx))
            self._speed_btns.append(btn)
            speed_row.addWidget(btn)

        self._slider = QSlider(Qt.Horizontal, self)
        self._slider.setRange(0, 10000)
        self._slider.setValue(0)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        self._slider.sliderReleased.connect(self._on_slider_released)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(6)
        layout.addWidget(self._btn_play)
        layout.addLayout(speed_row)
        layout.addWidget(self._slider, 1)

    # ── public ────────────────────────────────────────────────────────────────

    def set_timezone(self, tz_mode: str) -> None:
        self._tz_mode = tz_mode or "none"

    def set_range(self, t_min: float, t_max: float) -> None:
        self._t_min = float(t_min)
        self._t_max = float(t_max)
        self._current = float(t_min)
        self._sync_slider()

    @property
    def current_time(self) -> float:
        return self._current

    def set_values_html(self, html: str) -> None:
        return

    def clear_values(self) -> None:
        return

    def stop(self) -> None:
        self._playing = False
        self._timer.stop()
        self._btn_play.setText("▶")

    def reset(self) -> None:
        self.stop()
        self._current = self._t_min
        self._sync_slider()
        self.time_changed.emit(self._current)

    # ── private ───────────────────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        if self._playing:
            self.stop()
            self.playback_paused.emit()
        else:
            if self._current >= self._t_max:
                self._current = self._t_min
            self._playing = True
            self._timer.start()
            self._btn_play.setText("⏸")
            self.playback_started.emit()

    def _tick(self) -> None:
        dt = (_TICK_MS / 1000.0) * self._speed
        self._current = min(self._current + dt, self._t_max)
        self._sync_slider()
        self.time_changed.emit(self._current)
        if self._current >= self._t_max:
            self.stop()

    def _set_speed_index(self, idx: int) -> None:
        self._speed = _SPEEDS[idx][1]
        for i, btn in enumerate(self._speed_btns):
            btn.setChecked(i == idx)

    def _on_slider_pressed(self) -> None:
        self._dragging = True

    def _on_slider_moved(self, value: int) -> None:
        span = self._t_max - self._t_min
        if span > 0:
            self._current = self._t_min + (value / 10000.0) * span
        self.time_changed.emit(self._current)

    def _on_slider_released(self) -> None:
        self._dragging = False

    def _sync_slider(self) -> None:
        if self._dragging:
            return
        span = self._t_max - self._t_min
        pos = int(10000 * (self._current - self._t_min) / span) if span > 0 else 0
        self._slider.blockSignals(True)
        self._slider.setValue(max(0, min(10000, pos)))
        self._slider.blockSignals(False)

