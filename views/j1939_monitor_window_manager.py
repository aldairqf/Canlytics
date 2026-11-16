from __future__ import annotations

import polars as pl

from views.base_window_manager import BaseWindowManager
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.j1939_monitor_viewmodel import J1939MonitorViewModel
from views.j1939_monitor_window import J1939MonitorWindow


class J1939MonitorWindowManager(BaseWindowManager):
    def __init__(self, vm: J1939MonitorViewModel, data_vm: LogDataViewModel) -> None:
        super().__init__()
        self._vm = vm
        self._data_vm = data_vm

    def _create_window(self) -> J1939MonitorWindow:
        window = J1939MonitorWindow(self._vm)
        self._vm.set_dataframe(self._data_vm.df)
        self._data_vm.dataframe_changed.connect(self._vm.set_dataframe)
        self._data_vm.dataframe_replaced.connect(self._on_dataframe_replaced)
        window.refresh_requested.connect(lambda: self._vm.analyze())
        return window

    def _on_window_destroyed(self, _obj=None) -> None:
        for signal, slot in (
            (self._data_vm.dataframe_changed, self._vm.set_dataframe),
            (self._data_vm.dataframe_replaced, self._on_dataframe_replaced),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._vm.release()
        super()._on_window_destroyed(_obj)

    def _on_dataframe_replaced(self, dataframe: pl.DataFrame | None) -> None:
        self._vm.set_dataframe(dataframe)
        self._vm.clear_snapshot()
        self._vm.analyze()

    def open_window(self) -> J1939MonitorWindow:
        window = super().open_window()
        if self._vm.analysis_running:
            window.analysis_started()
        else:
            self._vm.analyze()
        return window
