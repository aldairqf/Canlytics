from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from core.dbc_manager import DbcManager
from viewmodels.table_viewmodel import TableViewModel


class _InterpretWorker(QObject):
    finished = QtSignal()

    def run(self) -> None:
        self.finished.emit()


class InterpretationViewModel(QObject):

    available_changed = QtSignal(bool)
    enabled_changed = QtSignal(bool)
    loading_changed = QtSignal(bool)

    def __init__(self, dbc_manager: DbcManager, table_vm: TableViewModel, parent: QObject | None = None):
        super().__init__(parent)
        self._dbc_manager = dbc_manager
        self._table_vm = table_vm

        self._available = bool(self._dbc_manager.active_entries())
        self._enabled = False
        self._loading = False

        self._thread: Optional[QThread] = None
        self._worker: Optional[_InterpretWorker] = None

        self._dbc_manager.entries_changed.connect(self._recompute_available)

    @property
    def available(self) -> bool:
        return self._available

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def loading(self) -> bool:
        return self._loading

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            if not self._available or self._enabled or self._loading:
                return
            self._start_enable()
            return

        if self._enabled or self._loading:
            self._enabled = False
            self._loading = False
            self.loading_changed.emit(False)
            self._table_vm.set_decode_context(self._dbc_manager, False)
            self.enabled_changed.emit(False)

    def shutdown(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    def _recompute_available(self) -> None:
        new_available = bool(self._dbc_manager.active_entries())
        if new_available == self._available:
            return

        self._available = new_available
        self.available_changed.emit(new_available)

        if not new_available and (self._enabled or self._loading):
            self.set_enabled(False)

        self._table_vm.set_decode_context(self._dbc_manager, self._enabled)

    def _start_enable(self) -> None:
        self._loading = True
        self.loading_changed.emit(True)

        self._worker = _InterpretWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._finish_enable)
        self._thread.finished.connect(self._cleanup_worker)

        self._thread.start()

    def _finish_enable(self) -> None:
        self._loading = False
        self.loading_changed.emit(False)

        if not self._available:
            self.set_enabled(False)
            return

        self._enabled = True
        self._table_vm.set_decode_context(self._dbc_manager, True)
        self.enabled_changed.emit(True)

    def _cleanup_worker(self) -> None:
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
