from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from views.base_window_manager import BaseWindowManager
from views.bit_activity_window import BitActivityWindow

if TYPE_CHECKING:
    from viewmodels.analysis_context_viewmodel import AnalysisContextViewModel
    from viewmodels.bit_activity_viewmodel import BitActivityViewModel


class BitActivityWindowManager(BaseWindowManager):
    def __init__(
        self,
        vm: BitActivityViewModel,
        *,
        analysis_context_vm: AnalysisContextViewModel | None = None,
        is_live: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self._vm = vm
        self._analysis_context_vm = analysis_context_vm
        self._is_live = is_live

    def _create_window(self) -> BitActivityWindow:
        return BitActivityWindow(
            self._vm,
            analysis_context_vm=self._analysis_context_vm,
            is_live=self._is_live,
            parent=None,
        )

    def open_window(self) -> BitActivityWindow:
        window = super().open_window()
        self._vm.activate()
        return window
