from __future__ import annotations

from views.base_window_manager import BaseWindowManager
from views.bus_statistics_window import BusStatisticsWindow
from viewmodels.bus_statistics_viewmodel import BusStatisticsViewModel


class BusStatisticsWindowManager(BaseWindowManager):
    def __init__(self, vm: BusStatisticsViewModel):
        super().__init__()
        self._vm = vm

    def _create_window(self) -> BusStatisticsWindow:
        return BusStatisticsWindow(self._vm)
