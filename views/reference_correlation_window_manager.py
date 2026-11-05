from __future__ import annotations

from services.candidate_interpretations import CandidateItem
from views.base_window_manager import BaseWindowManager
from views.reference_correlation_window import ReferenceCorrelationWindow


class ReferenceCorrelationWindowManager(BaseWindowManager):
    def __init__(
        self,
        *,
        vm: object,
        data_vm: object,
        candidates_vm: object,
        markers_vm: object,
        analysis_context_vm: object,
        dbc_signal_options_getter: object,
    ) -> None:
        super().__init__()
        self._vm = vm
        self._data_vm = data_vm
        self._candidates_vm = candidates_vm
        self._markers_vm = markers_vm
        self._analysis_context_vm = analysis_context_vm
        self._dbc_signal_options_getter = dbc_signal_options_getter
        self._candidate: CandidateItem | None = None

    def open_window_for_candidate(
        self, candidate: CandidateItem
    ) -> ReferenceCorrelationWindow | None:
        if self._vm.running:
            return self.open_window() if self._window is not None else None
        self._candidate = candidate
        window = self.open_window()
        window.set_candidate(candidate)
        return window

    def _create_window(self) -> ReferenceCorrelationWindow:
        if self._candidate is None:
            raise RuntimeError("reference correlation needs a selected candidate")
        return ReferenceCorrelationWindow(
            self._vm,
            self._candidate,
            dataframe_getter=lambda: self._data_vm.df,
            candidates_vm=self._candidates_vm,
            markers_vm=self._markers_vm,
            analysis_context_vm=self._analysis_context_vm,
            dbc_signal_options_getter=self._dbc_signal_options_getter,
        )
