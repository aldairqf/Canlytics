from __future__ import annotations

from views.mux_detection_window import MuxDetectionWindow


class MuxDetectionWindowManager:
    def __init__(self, *, vm, time_config_vm, get_timezone):
        self._vm = vm
        self._time_config_vm = time_config_vm
        self._get_timezone = get_timezone
        self._window: MuxDetectionWindow | None = None

    def open_window(self) -> MuxDetectionWindow:
        if self._window is None:
            self._window = MuxDetectionWindow(
                self._vm,
                time_config_vm=self._time_config_vm,
                timezone_mode=self._get_timezone(),
                parent=None,
            )
            self._window.destroyed.connect(self._on_window_destroyed)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window

    def _on_window_destroyed(self, _obj=None) -> None:
        self._window = None
