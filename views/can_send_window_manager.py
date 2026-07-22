from __future__ import annotations

from views.base_window_manager import BaseWindowManager
from views.can_send_window import CanSendWindow


class CanSendWindowManager(BaseWindowManager):
    def __init__(self, *, vm, dbc_manager):
        super().__init__()
        self._vm = vm
        self._dbc_manager = dbc_manager

    def _create_window(self) -> CanSendWindow:
        return CanSendWindow(self._vm, dbc_manager=self._dbc_manager, parent=None)
