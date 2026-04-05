from __future__ import annotations

from views.analyze_data_window import AnalyzeDataWindow


class AnalyzeDataWindowManager:
    def __init__(self, *, vm, parent=None):
        self._vm = vm
        self._parent = parent
        self._window: AnalyzeDataWindow | None = None

    def open_window(self) -> AnalyzeDataWindow:
        if self._window is None:
            self._window = AnalyzeDataWindow(self._vm, parent=self._parent)
            self._window.destroyed.connect(self._on_window_destroyed)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window

    def _on_window_destroyed(self, _obj=None) -> None:
        self._window = None
