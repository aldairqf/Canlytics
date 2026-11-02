from __future__ import annotations

from config.app_config import get_text
from models.analysis_context import AnalysisContext
from views.base_window_manager import BaseWindowManager
from views.candidate_interpretations_window import CandidateInterpretationsWindow


class CandidateInterpretationsWindowManager(BaseWindowManager):
    def __init__(
        self, *, vm, data_vm, time_config_vm, session_state, get_timezone,
        plot_manager=None, real_time_analysis_manager=None, analysis_context_vm=None,
        mux_configuration_vm=None,
        time_range_vm=None,
    ):
        super().__init__()
        self._vm = vm
        self._data_vm = data_vm
        self._time_config_vm = time_config_vm
        self._session_state = session_state
        self._get_timezone = get_timezone
        self._plot_manager = plot_manager
        self._real_time_analysis_manager = real_time_analysis_manager
        self._analysis_context_vm = analysis_context_vm
        self._mux_configuration_vm = mux_configuration_vm
        self._time_range_vm = time_range_vm

    def _create_window(self) -> CandidateInterpretationsWindow:
        # Only feed the accumulated dataframe to the viewmodel while a window
        # is actually open -- otherwise every incoming chunk (~10 Hz) recomputes
        # unique CAN ids over the whole log and wipes the candidate results for
        # a window nobody has open. Primed once here, then kept live until close.
        self._vm.reset_dataframe(self._data_vm.df)
        self._data_vm.dataframe_changed.connect(self._vm.set_dataframe)
        self._data_vm.dataframe_replaced.connect(self._vm.reset_dataframe)
        return CandidateInterpretationsWindow(
            self._vm,
            time_config_vm=self._time_config_vm,
            session_state=self._session_state,
            plot_manager=self._plot_manager,
            real_time_analysis_manager=self._real_time_analysis_manager,
            analysis_context_vm=self._analysis_context_vm,
            mux_configuration_vm=self._mux_configuration_vm,
            time_range_vm=self._time_range_vm,
            timezone_mode=self._get_timezone(),
            parent=None,
        )

    def _on_window_destroyed(self, _obj=None) -> None:
        try:
            self._data_vm.dataframe_changed.disconnect(self._vm.set_dataframe)
        except (TypeError, RuntimeError):
            pass
        try:
            self._data_vm.dataframe_replaced.disconnect(self._vm.reset_dataframe)
        except (TypeError, RuntimeError):
            pass
        super()._on_window_destroyed(_obj)

    def open_window_for_can_id(self, can_id: str, *, source: str | None = None):
        """P1 handoff: open (or reuse/raise) the window already scoped to one CAN ID."""
        window = self.open_window()
        window.set_checked_can_ids({can_id})
        if source:
            window.statusBar().showMessage(get_text("handoff_scoped_status").format(can_id=can_id, source=source), 6000)
        return window

    def open_window_for_context(self, context: AnalysisContext):
        """Scope Candidate to the evidence selected in another analysis tool."""
        if context.can_id is None:
            return self.open_window()
        ranges = tuple(
            time_range
            for time_range in (context.range_a, context.range_b)
            if time_range is not None
        )
        if ranges:
            self._vm.set_time_ranges(ranges)
        elif context.time_range is not None:
            self._vm.set_time_ranges(())
            if self._time_range_vm is not None:
                self._time_range_vm.set_time_range(*context.time_range)
        else:
            self._vm.set_time_ranges(())
        self._vm.set_byte_indices(context.byte_indices)
        if self._analysis_context_vm is not None and self._analysis_context_vm.context != context:
            self._analysis_context_vm.set_context(context)
        window = self.open_window()
        window.set_checked_can_ids({context.can_id})
        window.statusBar().showMessage(
            get_text("handoff_scoped_status").format(
                can_id=context.can_id,
                source=context.source_window or get_text("analysis_context_source_unknown"),
            ),
            6000,
        )
        return window
