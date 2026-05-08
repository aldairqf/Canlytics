from __future__ import annotations

from views.realtime_analysis_window import RealTimeAnalysisWindow


class RealTimeAnalysisWindowManager:
    def __init__(self, *, analysis_vm, dbc_manager, time_config_vm, parent=None):
        self._analysis_vm = analysis_vm
        self._dbc_manager = dbc_manager
        self._time_config_vm = time_config_vm
        self._window: RealTimeAnalysisWindow | None = None

    def open_window(self) -> RealTimeAnalysisWindow:
        if self._window is None:
            self._window = RealTimeAnalysisWindow(
                self._analysis_vm,
                self._dbc_manager,
                self._time_config_vm,
                parent=None,
            )
            self._window.destroyed.connect(self._on_window_destroyed)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window

    def _on_window_destroyed(self, _obj=None) -> None:
        self._window = None
