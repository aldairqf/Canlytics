from __future__ import annotations

from views.base_window_manager import BaseWindowManager
from views.candidate_interpretations_window import CandidateInterpretationsWindow


class CandidateInterpretationsWindowManager(BaseWindowManager):
    def __init__(self, *, vm, data_vm, time_config_vm, session_state, get_timezone, plot_manager=None):
        super().__init__()
        self._vm = vm
        self._data_vm = data_vm
        self._time_config_vm = time_config_vm
        self._session_state = session_state
        self._get_timezone = get_timezone
        self._plot_manager = plot_manager

    def _create_window(self) -> CandidateInterpretationsWindow:
        # Only feed the accumulated dataframe to the viewmodel while a window
        # is actually open -- otherwise every incoming chunk (~10 Hz) recomputes
        # unique CAN ids over the whole log and wipes the candidate results for
        # a window nobody has open. Primed once here, then kept live until close.
        self._vm.set_dataframe(self._data_vm.df)
        self._data_vm.dataframe_changed.connect(self._vm.set_dataframe)
        return CandidateInterpretationsWindow(
            self._vm,
            time_config_vm=self._time_config_vm,
            session_state=self._session_state,
            plot_manager=self._plot_manager,
            timezone_mode=self._get_timezone(),
            parent=None,
        )

    def _on_window_destroyed(self, _obj=None) -> None:
        try:
            self._data_vm.dataframe_changed.disconnect(self._vm.set_dataframe)
        except (TypeError, RuntimeError):
            pass
        super()._on_window_destroyed(_obj)
