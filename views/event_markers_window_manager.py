from __future__ import annotations

from typing import Callable

from views.base_window_manager import BaseWindowManager
from views.event_markers_window import EventMarkersWindow
from views.range_diff_window_manager import RangeDiffWindowManager
from viewmodels.event_markers_viewmodel import EventMarkersViewModel
from viewmodels.range_diff_viewmodel import RangeDiffViewModel


class EventMarkersWindowManager(BaseWindowManager):
    def __init__(
        self,
        *,
        vm: EventMarkersViewModel,
        timestamp_getter: Callable[[], float | None],
        range_diff_vm: RangeDiffViewModel,
        range_diff_manager: RangeDiffWindowManager,
    ) -> None:
        super().__init__()
        self._vm = vm
        self._timestamp_getter = timestamp_getter
        self._range_diff_vm = range_diff_vm
        self._range_diff_manager = range_diff_manager

    def _create_window(self) -> EventMarkersWindow:
        return EventMarkersWindow(
            self._vm,
            timestamp_getter=self._timestamp_getter,
            range_diff_vm=self._range_diff_vm,
            range_diff_manager=self._range_diff_manager,
        )
