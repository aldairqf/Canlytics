from __future__ import annotations

from views.analyze_data_window import AnalyzeDataWindow
from views.base_window_manager import BaseWindowManager


class AnalyzeDataWindowManager(BaseWindowManager):
    def __init__(self, *, vm, time_config_vm, get_timezone, parent=None):
        super().__init__()
        self._vm = vm
        self._time_config_vm = time_config_vm
        self._get_timezone = get_timezone

    def _create_window(self) -> AnalyzeDataWindow:
        return AnalyzeDataWindow(
            self._vm,
            time_config_vm=self._time_config_vm,
            timezone_mode=self._get_timezone(),
            parent=None,
        )
