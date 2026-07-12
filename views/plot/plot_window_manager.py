from __future__ import annotations

from typing import Callable

import polars as pl
from PySide6.QtWidgets import QMainWindow

from models.frame_selector import FrameSelector
from models.signal import Signal
from services.dbc_manager import DbcManager
from services.plot_config import parse_signal_data
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.plot_viewmodel import PlotViewModel
from viewmodels.table_model import TableModel
from viewmodels.time_config_viewmodel import TimeConfigViewModel
from viewmodels.view_signal import ViewSignal
from views.plot.add_to_plot_menu import make_view_signal, show_add_to_plot_menu
from views.plot.plot_window import PlotWindow


class PlotWindowManager:
    def __init__(
        self,
        parent: QMainWindow,
        *,
        data_vm: LogDataViewModel,
        dbc_manager: DbcManager,
        table_model: TableModel,
        get_timezone: Callable[[], str],
        interpret_enabled: Callable[[], bool],
        time_config_vm: TimeConfigViewModel | None = None,
    ):
        self._parent = parent
        self._data_vm = data_vm
        self._dbc_manager = dbc_manager
        self._table_model = table_model
        self._get_timezone = get_timezone
        self._interpret_enabled = interpret_enabled
        self._time_config_vm = time_config_vm

        self._plot_windows: dict[PlotWindow, PlotViewModel] = {}
        self._last_plot_window: PlotWindow | None = None

    def set_timezone(self, tz: str) -> None:
        for window in list(self._plot_windows.keys()):
            window._set_timezone(tz)

    def open_plot_window(self) -> tuple[PlotWindow, PlotViewModel]:
        df = self._data_vm.df
        if df is None or df.is_empty():
            df = pl.DataFrame()

        plot_vm = PlotViewModel(df)
        self._data_vm.dataframe_changed.connect(plot_vm.set_dataframe)

        win = PlotWindow(
            plot_vm,
            dbc_manager=self._dbc_manager,
            time_config_vm=self._time_config_vm,
        )
        win.closed.connect(lambda: self._on_plot_closed(win))

        self._plot_windows[win] = plot_vm
        self._last_plot_window = win
        win.show()
        return win, plot_vm

    def close_all(self) -> None:
        for win in list(self._plot_windows.keys()):
            win.close()

    def _on_plot_closed(self, window: PlotWindow) -> None:
        plot_vm = self._plot_windows.pop(window, None)
        if plot_vm:
            try:
                self._data_vm.dataframe_changed.disconnect(plot_vm.set_dataframe)
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

        show_add_to_plot_menu(
            self._parent, global_pos, self,
            lambda: self._build_view_signal(signal_def),
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
