from __future__ import annotations

from typing import Callable

import polars as pl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu, QMainWindow

from models.frame_selector import FrameSelector
from models.signal import Signal
from models.view_signal import ViewSignal
from services.contracts import DbcService
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.plot_viewmodel import PlotViewModel
from views.plot.plot_window import PlotWindow
from viewmodels.table_model import TableModel
from config.app_config import get_text


class PlotWindowManager:
    def __init__(
        self,
        parent: QMainWindow,
        *,
        data_vm: LogDataViewModel,
        dbc_manager: DbcService,
        table_model: TableModel,
        get_timezone: Callable[[], str],
        interpret_enabled: Callable[[], bool],
    ):
        self._parent = parent
        self._data_vm = data_vm
        self._dbc_manager = dbc_manager
        self._table_model = table_model
        self._get_timezone = get_timezone
        self._interpret_enabled = interpret_enabled

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
            timezone_mode=self._get_timezone(),
        )
        win.closed.connect(lambda: self._on_plot_closed(win))

        self._plot_windows[win] = plot_vm
        self._last_plot_window = win
        win.show()
        return win, plot_vm

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

        menu = QMenu(self._parent)
        add_new = menu.addAction(get_text("add_new_graph"))
        add_last = menu.addAction(get_text("add_last_graph"))
        action = menu.exec(global_pos)

        if action == add_new:
            self._add_graph_from_signal(signal_def, use_last=False)
        elif action == add_last:
            self._add_graph_from_signal(signal_def, use_last=True)

    def _add_graph_from_signal(self, signal_def: dict, use_last: bool) -> None:
        if use_last and self._last_plot_window in self._plot_windows:
            plot_vm = self._plot_windows[self._last_plot_window]
            win = self._last_plot_window
        else:
            win, plot_vm = self.open_plot_window()

        base_name = signal_def.get("name", "Signal")
        name = self._unique_signal_name(plot_vm, base_name)

        parsed = plot_vm.parse_signal_data(signal_def)
        sig = Signal(**{**parsed["signal"], "name": name})
        selector = FrameSelector(**parsed["selector"])

        if selector.selected_id is None:
            selector.selected_id = sig.can_id
        if sig.can_id is None:
            sig.can_id = selector.selected_id

        win.renderer.request_autorange()

        view_signal = ViewSignal(
            signal=sig,
            selector=selector,
            color=QColor("cyan"),
            line_style="Solid",
            line_width=2,
        )
        plot_vm.upsert_signal(view_signal)
        self._last_plot_window = win

    @staticmethod
    def _unique_signal_name(plot_vm: PlotViewModel, base: str) -> str:
        name = base
        index = 1
        while name in plot_vm.signals:
            name = f"{base}_{index}"
            index += 1
        return name
