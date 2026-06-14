from __future__ import annotations

from views.base_window_manager import BaseWindowManager
from views.candidate_interpretations_window import CandidateInterpretationsWindow


class CandidateInterpretationsWindowManager(BaseWindowManager):
    def __init__(self, *, vm, time_config_vm, session_state, get_timezone, plot_manager=None):
        super().__init__()
        self._vm = vm
        self._time_config_vm = time_config_vm
        self._session_state = session_state
        self._get_timezone = get_timezone
        self._plot_manager = plot_manager

    def _create_window(self) -> CandidateInterpretationsWindow:
        return CandidateInterpretationsWindow(
            self._vm,
            time_config_vm=self._time_config_vm,
            session_state=self._session_state,
            plot_manager=self._plot_manager,
            timezone_mode=self._get_timezone(),
            parent=None,
        )
