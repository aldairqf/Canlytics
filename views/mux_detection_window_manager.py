from __future__ import annotations

from views.base_window_manager import BaseWindowManager
from views.mux_detection_window import MuxDetectionWindow


class MuxDetectionWindowManager(BaseWindowManager):
    def __init__(self, *, vm, time_config_vm, get_timezone, time_range_vm=None):
        super().__init__()
        self._vm = vm
        self._time_config_vm = time_config_vm
        self._get_timezone = get_timezone
        self._time_range_vm = time_range_vm

    def _create_window(self) -> MuxDetectionWindow:
        return MuxDetectionWindow(
            self._vm,
            time_config_vm=self._time_config_vm,
            timezone_mode=self._get_timezone(),
            time_range_vm=self._time_range_vm,
            parent=None,
        )
