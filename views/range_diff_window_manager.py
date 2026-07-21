from __future__ import annotations

from config.app_config import get_text
from views.base_window_manager import BaseWindowManager
from views.range_diff_window import RangeDiffWindow


class RangeDiffWindowManager(BaseWindowManager):
    def __init__(
        self, *, vm, time_config_vm, get_timezone, session_state=None,
        plot_manager=None, candidate_interpretations_manager=None,
    ):
        super().__init__()
        self._vm = vm
        self._time_config_vm = time_config_vm
        self._get_timezone = get_timezone
        self._session_state = session_state
        self._plot_manager = plot_manager
        self._candidate_interpretations_manager = candidate_interpretations_manager

    def _create_window(self) -> RangeDiffWindow:
        return RangeDiffWindow(
            self._vm,
            time_config_vm=self._time_config_vm,
            session_state=self._session_state,
            timezone_mode=self._get_timezone(),
            plot_manager=self._plot_manager,
            candidate_interpretations_manager=self._candidate_interpretations_manager,
            parent=None,
        )

    def open_window_live(self, *, source: str | None = None):
        """P1.3 handoff (e.g. Real-Time's 'Compare from now' shortcut): open the
        window and start a Live session immediately if one isn't already running."""
        window = self.open_window()
        if not self._vm.is_live:
            self._vm.capture_live_baseline()
        if source:
            window.statusBar().showMessage(get_text("handoff_live_status").format(source=source), 6000)
        return window
