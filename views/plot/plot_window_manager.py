from __future__ import annotations

from typing import Callable

import polars as pl
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMainWindow

from models.frame_selector import FrameSelector
from models.signal import Signal
from config.app_config import get_text
from viewmodels.dbc_manager_viewmodel import DbcManagerViewModel
from services.plot_config import parse_signal_data
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.plot_viewmodel import PlotViewModel
from viewmodels.state_tracker_viewmodel import StateTrackerViewModel
from viewmodels.table_model import TableModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from viewmodels.view_signal import ViewSignal
from views.plot.add_to_plot_menu import (
    analysis_context_for_view_signal,
    analysis_send_destinations,
    make_view_signal,
    plot_send_destinations,
    show_send_to_menu,
)
from views.plot.plot_window import PlotWindow
from views.base_window_manager import enable_window_geometry_persistence


class PlotWindowManager:
    def __init__(
        self,
        parent: QMainWindow,
        *,
        data_vm: LogDataViewModel,
        dbc_manager: DbcManagerViewModel,
        table_model: TableModel,
        get_timezone: Callable[[], str],
        interpret_enabled: Callable[[], bool],
        time_config_vm: TimeConfigViewModel | None = None,
        connection_vm=None,
        session_state: object | None = None,
        analysis_context_vm=None,
        time_cursor_vm=None,
        event_markers_vm=None,
    ):
        self._parent = parent
        self._data_vm = data_vm
        self._dbc_manager = dbc_manager
        self._table_model = table_model
        self._get_timezone = get_timezone
        self._interpret_enabled = interpret_enabled
        self._time_config_vm = time_config_vm
        self._connection_vm = connection_vm
        self._session_state = session_state
        self._analysis_context_vm = analysis_context_vm
        self._time_cursor_vm = time_cursor_vm
        self._event_markers_vm = event_markers_vm

        self._plot_windows: dict[PlotWindow, PlotViewModel] = {}
        self._state_tracker_vms: dict[PlotWindow, StateTrackerViewModel] = {}
        self._geometry_filters: dict[PlotWindow, QObject] = {}
        self._last_plot_window: PlotWindow | None = None

    def open_plot_window(self) -> tuple[PlotWindow, PlotViewModel]:
        df = self._data_vm.df
        if df is None or df.is_empty():
            df = pl.DataFrame()

        plot_vm = PlotViewModel(df)
        state_tracker_vm = StateTrackerViewModel(df)
        self._data_vm.dataframe_changed.connect(plot_vm.set_dataframe)
        self._data_vm.dataframe_replaced.connect(plot_vm.reset_dataframe)
        self._data_vm.dataframe_changed.connect(state_tracker_vm.set_dataframe)
        self._data_vm.dataframe_replaced.connect(state_tracker_vm.reset_dataframe)
        self._data_vm.rows_appended.connect(state_tracker_vm.append_rows)
        if self._connection_vm is not None:
            self._connection_vm.chunk_ready.connect(plot_vm.ingest_raw_chunk)

        win = PlotWindow(
            plot_vm,
            dbc_manager=self._dbc_manager,
            time_config_vm=self._time_config_vm,
            analysis_context_vm=self._analysis_context_vm,
            realtime_enabled=self._real_time_analysis_available,
            time_cursor_vm=self._time_cursor_vm,
            event_markers_vm=self._event_markers_vm,
            state_tracker_vm=state_tracker_vm,
        )
        win.closed.connect(lambda: self._on_plot_closed(win))
        self._data_vm.dataframe_replaced.connect(win.refresh_time_origin)

        self._plot_windows[win] = plot_vm
        self._state_tracker_vms[win] = state_tracker_vm
        if self._session_state is not None:
            self._geometry_filters[win] = enable_window_geometry_persistence(
                win, self._session_state, "PlotWindow"
            )
        self._last_plot_window = win
        win.show()
        return win, plot_vm

    def close_all(self) -> None:
        for win in list(self._plot_windows.keys()):
            win.close()

    def _real_time_analysis_available(self) -> bool:
        if self._connection_vm is not None and self._connection_vm.running:
            return True
        dataframe = self._data_vm.df
        return dataframe is not None and not dataframe.is_empty()

    def _on_plot_closed(self, window: PlotWindow) -> None:
        self._geometry_filters.pop(window, None)
        plot_vm = self._plot_windows.pop(window, None)
        state_tracker_vm = self._state_tracker_vms.pop(window, None)
        if plot_vm:
            try:
                self._data_vm.dataframe_replaced.disconnect(window.refresh_time_origin)
            except (TypeError, RuntimeError):
                pass
            try:
                self._data_vm.dataframe_changed.disconnect(plot_vm.set_dataframe)
            except (TypeError, RuntimeError):
                pass
            try:
                self._data_vm.dataframe_replaced.disconnect(plot_vm.reset_dataframe)
            except (TypeError, RuntimeError):
                pass
            if state_tracker_vm is not None:
                for signal, slot in (
                    (self._data_vm.dataframe_changed, state_tracker_vm.set_dataframe),
                    (self._data_vm.dataframe_replaced, state_tracker_vm.reset_dataframe),
                    (self._data_vm.rows_appended, state_tracker_vm.append_rows),
                ):
                    try:
                        signal.disconnect(slot)
                    except (TypeError, RuntimeError):
                        pass
            if self._connection_vm is not None:
                try:
                    self._connection_vm.chunk_ready.disconnect(plot_vm.ingest_raw_chunk)
                except (TypeError, RuntimeError):
                    pass
        if self._last_plot_window is window:
            self._last_plot_window = next(iter(self._plot_windows), None)

    def on_decode_context(self, row: int, line_index: int, global_pos) -> None:
        if not self._interpret_enabled():
            return

        item = self._table_model.get_decode_item_for_line(row, line_index)
        if not item:
            return

        signal_def = item.get("signal_def")
        if not signal_def:
            return

        row_can_id = self._table_model.get_row_can_id(row)
        if row_can_id:
            signal_def = {**signal_def, "can_id": row_can_id}

        view_signal = self._build_view_signal(signal_def)
        context = analysis_context_for_view_signal(view_signal, "Main table")
        destinations = plot_send_destinations(
            self,
            lambda: view_signal,
            analysis_context_vm=self._analysis_context_vm,
            context=context,
                source_window=get_text("analysis_source_main_table"),
        )
        if self._analysis_context_vm is not None:
            destinations.update(analysis_send_destinations(
                self._analysis_context_vm,
                context,
                realtime_enabled=self._real_time_analysis_available(),
            ))
        show_send_to_menu(
            self._parent,
            global_pos,
            destinations,
        )

    @staticmethod
    def _build_view_signal(signal_def: dict) -> ViewSignal:
        parsed = parse_signal_data(signal_def)
        sig = Signal(**parsed["signal"])
        selector = FrameSelector(**parsed["selector"])
        return make_view_signal(sig, selector)

    def add_view_signal(self, view_signal: ViewSignal, *, use_last: bool) -> tuple[PlotWindow, PlotViewModel]:
        win, plot_vm = self._resolve_target_window(use_last)
        self._store_view_signal(win, plot_vm, view_signal)
        return win, plot_vm

    def _store_view_signal(
        self,
        win: PlotWindow,
        plot_vm: PlotViewModel,
        view_signal: ViewSignal,
    ) -> None:
        unique_name = self._unique_signal_name(plot_vm, view_signal.signal.name or "Signal")
        view_signal.signal.name = unique_name

        if view_signal.selector.selected_id is None:
            view_signal.selector.selected_id = view_signal.signal.can_id
        if view_signal.signal.can_id is None:
            view_signal.signal.can_id = view_signal.selector.selected_id

        view_signal.color = plot_vm.next_color()

        win.renderer.request_autorange()
        plot_vm.upsert_signal(view_signal)
        self._last_plot_window = win

    def _resolve_target_window(self, use_last: bool) -> tuple[PlotWindow, PlotViewModel]:
        if use_last and self._last_plot_window in self._plot_windows:
            return self._last_plot_window, self._plot_windows[self._last_plot_window]
        return self.open_plot_window()

    @staticmethod
    def _unique_signal_name(plot_vm: PlotViewModel, base: str) -> str:
        name = base
        index = 1
        while name in plot_vm.signals:
            name = f"{base}_{index}"
            index += 1
        return name
