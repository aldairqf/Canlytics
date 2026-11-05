from __future__ import annotations

from collections.abc import Callable

from config.app_config import get_text
from views.base_window_manager import BaseWindowManager
from views.realtime_analysis_window import RealTimeAnalysisWindow
from viewmodels.dbc_manager_viewmodel import DbcManagerViewModel


class RealTimeAnalysisWindowManager(BaseWindowManager):
    def __init__(
        self,
        *,
        analysis_vm,
        dbc_manager: DbcManagerViewModel,
        time_config_vm,
        get_timezone,
        is_live: Callable[[], bool],
        parent=None,
        range_diff_manager=None,
        mux_configuration_vm=None,
        time_cursor_vm=None,
        event_markers_vm=None,
        data_vm=None,
        connection_vm=None,
    ):
        super().__init__()
        self._analysis_vm = analysis_vm
        self._time_config_vm = time_config_vm
        self._get_timezone = get_timezone
        self._is_live = is_live
        self._dbc_manager = dbc_manager
        self._range_diff_manager = range_diff_manager
        self._mux_configuration_vm = mux_configuration_vm
        self._time_cursor_vm = time_cursor_vm
        self._event_markers_vm = event_markers_vm
        self._data_vm = data_vm
        self._connection_vm = connection_vm
        self._suspend_offline_reindex = False
        self._frame_context_handler: Callable[[object, int, object], None] | None = None
        if self._data_vm is not None:
            self._data_vm.dataframe_replaced.connect(self._on_offline_dataframe_replaced)
            self._data_vm.rows_appended.connect(self._on_offline_rows_appended)
        if self._connection_vm is not None:
            self._connection_vm.running_changed.connect(self._on_connection_running_changed)

    def is_live(self) -> bool:
        return self._is_live()

    def can_open(self) -> bool:
        if self.is_live():
            return True
        dataframe = self._data_vm.df if self._data_vm is not None else None
        return dataframe is not None and not dataframe.is_empty()

    def _create_window(self) -> RealTimeAnalysisWindow:
        self._analysis_vm.set_enabled(True)
        try:
            live = self.is_live()
            if live:
                self._analysis_vm.set_live_mode()
            elif self._data_vm is not None:
                self._analysis_vm.set_offline_dataframe(self._data_vm.df)
            window = RealTimeAnalysisWindow(
                self._analysis_vm,
                self._dbc_manager,
                parent=None,
                range_diff_manager=self._range_diff_manager,
                time_config_vm=self._time_config_vm,
                timezone_mode=self._get_timezone(),
                mux_configuration_vm=self._mux_configuration_vm,
                time_cursor_vm=self._time_cursor_vm,
                event_markers_vm=self._event_markers_vm,
                offline_mode=not live and self._data_vm is not None,
            )
            if self._frame_context_handler is not None:
                window.table.frame_context_requested.connect(self._frame_context_handler)
            return window
        except Exception:
            self._analysis_vm.set_enabled(False)
            raise

    def _on_offline_dataframe_replaced(self, dataframe) -> None:
        if (
            self._window is not None
            and not self.is_live()
            and not self._suspend_offline_reindex
        ):
            self._analysis_vm.set_offline_dataframe(dataframe)

    def _on_offline_rows_appended(self, _delta, _new_ids) -> None:
        if (
            self._window is not None
            and not self.is_live()
            and self._data_vm is not None
            and not self._suspend_offline_reindex
        ):
            self._analysis_vm.set_offline_dataframe(self._data_vm.df)

    def _on_connection_running_changed(self, running: bool) -> None:
        if self._window is None:
            return
        if running:
            self._analysis_vm.set_live_mode()
            self._window.set_offline_mode(False)
            return
        if self._data_vm is not None:
            self._suspend_offline_reindex = True
            try:
                self._data_vm.flush_pending()
            finally:
                self._suspend_offline_reindex = False
            self._analysis_vm.set_offline_dataframe(self._data_vm.df)
            self._window.set_offline_mode(True)

    def _on_window_destroyed(self, _obj: object = None) -> None:
        try:
            self._analysis_vm.set_enabled(False)
        except RuntimeError:
            pass  # app teardown: the VM's timers can be gone before the window
        super()._on_window_destroyed(_obj)

    def set_range_diff_manager(self, range_diff_manager) -> None:
        # Breaks a 3-way construction cycle in main_window.py's composition root
        # (RealTime -> RangeDiff -> Candidate -> RealTime): range_diff_manager is
        # built after this manager, so it's wired in afterwards instead of via __init__.
        self._range_diff_manager = range_diff_manager

    def set_frame_context_handler(
        self, handler: Callable[[object, int, object], None]
    ) -> None:
        self._frame_context_handler = handler

    def open_window_for_can_id(self, can_id: str, *, source: str | None = None):
        """P1 handoff: open (or reuse/raise) the window already scoped to one CAN ID."""
        window = self.open_window()
        window.set_checked_can_ids({can_id})
        if source:
            window.statusBar().showMessage(get_text("handoff_scoped_status").format(can_id=can_id, source=source), 6000)
        return window
