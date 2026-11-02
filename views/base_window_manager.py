from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QEvent, QObject
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)
_GEOMETRY_PREFS_KEY = "window_geometry"


class _GeometrySaveFilter(QObject):
    def __init__(self, session_state: object, window_key: str, parent: QWidget):
        super().__init__(parent)
        self._session_state = session_state
        self._window_key = window_key

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Close:
            geometry = watched.saveGeometry().toHex().data().decode("ascii")
            prefs = self._session_state.get_window_prefs(_GEOMETRY_PREFS_KEY)
            prefs[self._window_key] = geometry
            self._session_state.set_window_prefs(_GEOMETRY_PREFS_KEY, prefs)
        return False


def enable_window_geometry_persistence(
    window: QWidget, session_state: object, window_key: str
) -> QObject:
    geometry = session_state.get_window_prefs(_GEOMETRY_PREFS_KEY).get(window_key)
    if isinstance(geometry, str) and geometry:
        window.restoreGeometry(QByteArray.fromHex(geometry.encode("ascii")))
    event_filter = _GeometrySaveFilter(session_state, window_key, window)
    window.installEventFilter(event_filter)
    return event_filter


class BaseWindowManager:
    """Lazily creates and reuses a single secondary window.

    Subclasses implement ``_create_window()``; this base handles the
    create-once / show / raise / activate cycle and resets the reference when
    the window is destroyed.
    """

    def __init__(self) -> None:
        self._window = None
        self._session_state = None
        self._geometry_key = type(self).__name__
        self._geometry_filter = None

    def _create_window(self):
        raise NotImplementedError

    def set_geometry_persistence(
        self, session_state: object, window_key: str | None = None
    ) -> None:
        self._session_state = session_state
        if window_key:
            self._geometry_key = window_key

    def open_window(self):
        if self._window is None:
            logger.debug("Opening %s (new instance)", type(self).__name__)
            self._window = self._create_window()
            if self._session_state is not None:
                self._geometry_filter = enable_window_geometry_persistence(
                    self._window, self._session_state, self._geometry_key
                )
            self._window.destroyed.connect(self._on_window_destroyed)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window

    def _on_window_destroyed(self, _obj=None) -> None:
        self._window = None
        self._geometry_filter = None
