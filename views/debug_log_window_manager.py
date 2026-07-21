from __future__ import annotations

from pathlib import Path

from services.app_logging import QtLogHandler
from services.session_state import SessionStateStore
from views.base_window_manager import BaseWindowManager
from views.debug_log_window import DebugLogWindow


class DebugLogWindowManager(BaseWindowManager):
    def __init__(
        self,
        *,
        qt_log_handler: QtLogHandler,
        log_path: Path | None = None,
        session_state: SessionStateStore | None = None,
    ):
        super().__init__()
        self._qt_log_handler = qt_log_handler
        self._log_path = log_path
        self._session_state = session_state

    def _create_window(self) -> DebugLogWindow:
        return DebugLogWindow(
            self._qt_log_handler, log_path=self._log_path, session_state=self._session_state, parent=None
        )
