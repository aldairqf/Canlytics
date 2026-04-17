from __future__ import annotations

from viewmodels.hmi_video_extractor_viewmodel import HmiVideoExtractorViewModel
from views.hmi_video_extractor_window import HmiVideoExtractorWindow


class HmiVideoExtractorWindowManager:
    def __init__(self):
        self._window: HmiVideoExtractorWindow | None = None
        self._vm: HmiVideoExtractorViewModel | None = None

    def open_window(self) -> HmiVideoExtractorWindow:
        if self._window is None:
            self._vm = HmiVideoExtractorViewModel()
            self._window = HmiVideoExtractorWindow(self._vm, parent=None)
            self._window.destroyed.connect(self._on_window_destroyed)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window

    def _on_window_destroyed(self, _obj=None) -> None:
        self._window = None
        self._vm = None
