from __future__ import annotations

from config.app_config import get_text
from views.base_window_manager import BaseWindowManager
from views.realtime_analysis_window import RealTimeAnalysisWindow


class RealTimeAnalysisWindowManager(BaseWindowManager):
    def __init__(self, *, analysis_vm, dbc_manager, parent=None, range_diff_manager=None):
        super().__init__()
        self._analysis_vm = analysis_vm
        self._dbc_manager = dbc_manager
        self._range_diff_manager = range_diff_manager

    def _create_window(self) -> RealTimeAnalysisWindow:
        return RealTimeAnalysisWindow(
            self._analysis_vm,
            self._dbc_manager,
            parent=None,
            range_diff_manager=self._range_diff_manager,
        )

    def set_range_diff_manager(self, range_diff_manager) -> None:
        # Breaks a 3-way construction cycle in main_window.py's composition root
        # (RealTime -> RangeDiff -> Candidate -> RealTime): range_diff_manager is
        # built after this manager, so it's wired in afterwards instead of via __init__.
        self._range_diff_manager = range_diff_manager

    def open_window_for_can_id(self, can_id: str, *, source: str | None = None):
        """P1 handoff: open (or reuse/raise) the window already scoped to one CAN ID."""
        window = self.open_window()
        window.set_checked_can_ids({can_id})
        if source:
            window.statusBar().showMessage(get_text("handoff_scoped_status").format(can_id=can_id, source=source), 6000)
        return window
