from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class BaseWindowManager:
    """Lazily creates and reuses a single secondary window.

    Subclasses implement ``_create_window()``; this base handles the
    create-once / show / raise / activate cycle and resets the reference when
    the window is destroyed.
    """

    def __init__(self) -> None:
        self._window = None

    def _create_window(self):
        raise NotImplementedError

    def open_window(self):
        if self._window is None:
            logger.debug("Opening %s (new instance)", type(self).__name__)
            self._window = self._create_window()
            self._window.destroyed.connect(self._on_window_destroyed)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window

    def _on_window_destroyed(self, _obj=None) -> None:
        self._window = None
