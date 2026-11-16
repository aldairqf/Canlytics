from __future__ import annotations

from views.active_re_window import ActiveReWindow
from views.base_window_manager import BaseWindowManager


class ActiveReWindowManager(BaseWindowManager):
    def __init__(self, vm, dbc_signal_options, working_dbc_name: str = ""):
        super().__init__()
        self._vm = vm
        self._dbc_signal_options = dbc_signal_options
        self._working_dbc_name = working_dbc_name

    def _create_window(self):
        return ActiveReWindow(self._vm, self._dbc_signal_options(), working_dbc_name=self._working_dbc_name)
