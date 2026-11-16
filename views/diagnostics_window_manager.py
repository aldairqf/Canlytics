from __future__ import annotations

from views.base_window_manager import BaseWindowManager
from views.diagnostics_window import DiagnosticsWindow


class DiagnosticsWindowManager(BaseWindowManager):
    def __init__(self, vm, connection_vm, dataframe_getter=None) -> None:
        super().__init__()
        self._vm = vm
        self._connection_vm = connection_vm
        self._dataframe_getter = dataframe_getter
        self._chunk_connection = None

    def _create_window(self) -> DiagnosticsWindow:
        window = DiagnosticsWindow(self._vm)
        self._chunk_connection = self._connection_vm.chunk_ready.connect(window.ingest_chunk)
        window.destroyed.connect(self._disconnect)
        return window

    def _disconnect(self, _window=None) -> None:
        connection = self._chunk_connection
        self._chunk_connection = None
        if connection is None:
            return
        try:
            self._connection_vm.chunk_ready.disconnect(connection)
        except (RuntimeError, TypeError):
            pass
        self._vm.reset_observer()

    def open_window(self) -> DiagnosticsWindow:
        if self._dataframe_getter is not None and not bool(getattr(self._connection_vm, "running", False)):
            self._vm.ensure_loaded_dataframe(self._dataframe_getter())
        return super().open_window()
