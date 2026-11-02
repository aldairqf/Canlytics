from __future__ import annotations

from views.base_window_manager import BaseWindowManager
from views.signal_coverage_window import SignalCoverageWindow


class SignalCoverageWindowManager(BaseWindowManager):
    def __init__(self, *, vm, plot_manager=None, analysis_context_vm=None, is_live=None):
        super().__init__()
        self._vm = vm
        self._plot_manager = plot_manager
        self._analysis_context_vm = analysis_context_vm
        self._is_live = is_live

    def _create_window(self) -> SignalCoverageWindow:
        return SignalCoverageWindow(
            self._vm,
            plot_manager=self._plot_manager,
            analysis_context_vm=self._analysis_context_vm,
            is_live=self._is_live,
            parent=None,
        )
