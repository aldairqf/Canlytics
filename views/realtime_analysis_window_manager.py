from __future__ import annotations

from views.base_window_manager import BaseWindowManager
from views.realtime_analysis_window import RealTimeAnalysisWindow


class RealTimeAnalysisWindowManager(BaseWindowManager):
    def __init__(self, *, analysis_vm, dbc_manager, parent=None):
        super().__init__()
        self._analysis_vm = analysis_vm
        self._dbc_manager = dbc_manager

    def _create_window(self) -> RealTimeAnalysisWindow:
        return RealTimeAnalysisWindow(
            self._analysis_vm,
            self._dbc_manager,
            parent=None,
        )
