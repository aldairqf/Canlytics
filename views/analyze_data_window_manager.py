from __future__ import annotations

from views.analyze_data_window import AnalyzeDataWindow
from views.base_window_manager import BaseWindowManager


class AnalyzeDataWindowManager(BaseWindowManager):
    def __init__(self, *, vm, data_vm, connection_vm, time_config_vm, get_timezone, mux_configuration_vm=None, time_range_vm=None, interpret_vm=None, resolve_message_name=None, parent=None):
        super().__init__()
        self._vm = vm
        self._data_vm = data_vm
        self._connection_vm = connection_vm
        self._time_config_vm = time_config_vm
        self._get_timezone = get_timezone
        self._mux_configuration_vm = mux_configuration_vm
        self._time_range_vm = time_range_vm
        self._interpret_vm = interpret_vm
        self._resolve_message_name = resolve_message_name

    def _create_window(self) -> AnalyzeDataWindow:
        self._vm.reset_dataframe(self._data_vm.df)
        self._vm.set_dataframe(self._data_vm.df)
        window = AnalyzeDataWindow(
            self._vm,
            time_config_vm=self._time_config_vm,
            timezone_mode=self._get_timezone(),
            mux_configuration_vm=self._mux_configuration_vm,
            time_range_vm=self._time_range_vm,
            interpret_vm=self._interpret_vm,
            resolve_message_name=self._resolve_message_name,
            parent=None,
        )
        self._data_vm.dataframe_changed.connect(self._vm.set_dataframe)
        self._data_vm.dataframe_replaced.connect(self._vm.reset_dataframe)
        self._connection_vm.chunk_ready.connect(self._vm.ingest_raw_chunk)
        return window

    def _on_window_destroyed(self, _obj=None) -> None:
        for signal, slot in (
            (self._data_vm.dataframe_changed, self._vm.set_dataframe),
            (self._data_vm.dataframe_replaced, self._vm.reset_dataframe),
            (self._connection_vm.chunk_ready, self._vm.ingest_raw_chunk),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._vm.reset_dataframe(None)
        super()._on_window_destroyed(_obj)
