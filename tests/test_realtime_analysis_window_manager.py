from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import polars as pl
from PySide6.QtCore import QObject, Signal

from views.realtime_analysis_window_manager import RealTimeAnalysisWindowManager


class _AnalysisVm:
    def __init__(self):
        self.enabled = []
        self.set_live_mode = Mock()

    def set_enabled(self, enabled):
        self.enabled.append(enabled)


class _TimeConfigVm(QObject):
    timezone_changed = Signal(str)


class _DataVm(QObject):
    dataframe_replaced = Signal(object)
    rows_appended = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.df = pl.DataFrame({"ID": ["100"]})
        self.flushed = 0

    def flush_pending(self):
        self.flushed += 1
        self.rows_appended.emit(pl.DataFrame(), ())


class _ConnectionVm(QObject):
    running_changed = Signal(bool)


class _Window(QObject):
    destroyed = Signal(object)

    def show(self):
        pass

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def set_offline_mode(self, enabled):
        self.offline_modes = getattr(self, "offline_modes", []) + [enabled]


class RealTimeAnalysisWindowManagerTests(unittest.TestCase):
    def test_reports_live_state_from_provider(self):
        manager = RealTimeAnalysisWindowManager(
            analysis_vm=_AnalysisVm(),
            dbc_manager=object(),
            time_config_vm=_TimeConfigVm(),
            get_timezone=lambda: "UTC",
            is_live=lambda: True,
        )

        self.assertTrue(manager.is_live())

    def test_reports_offline_state_from_provider(self):
        manager = RealTimeAnalysisWindowManager(
            analysis_vm=_AnalysisVm(),
            dbc_manager=object(),
            time_config_vm=_TimeConfigVm(),
            get_timezone=lambda: "UTC",
            is_live=lambda: False,
        )

        self.assertFalse(manager.is_live())

    def test_offline_window_is_available_only_when_a_log_is_loaded(self):
        data_vm = _DataVm()
        manager = RealTimeAnalysisWindowManager(
            analysis_vm=_AnalysisVm(),
            dbc_manager=object(),
            time_config_vm=_TimeConfigVm(),
            get_timezone=lambda: "UTC",
            is_live=lambda: False,
            data_vm=data_vm,
        )
        self.assertTrue(manager.can_open())
        data_vm.df = pl.DataFrame()
        self.assertFalse(manager.can_open())

    def test_passes_timezone_configuration_to_window(self):
        analysis_vm = _AnalysisVm()
        time_vm = _TimeConfigVm()
        manager = RealTimeAnalysisWindowManager(
            analysis_vm=analysis_vm,
            dbc_manager=object(),
            time_config_vm=time_vm,
            get_timezone=lambda: "America/Lima",
            is_live=lambda: True,
        )
        window = _Window()

        with patch(
            "views.realtime_analysis_window_manager.RealTimeAnalysisWindow",
            return_value=window,
        ) as constructor:
            manager.open_window()

        self.assertIs(constructor.call_args.kwargs["time_config_vm"], time_vm)
        self.assertEqual(constructor.call_args.kwargs["timezone_mode"], "America/Lima")

    def test_offline_open_builds_index_from_loaded_dataframe(self):
        analysis_vm = _AnalysisVm()
        analysis_vm.set_offline_dataframe = Mock()
        analysis_vm.set_live_mode = Mock()
        data_vm = _DataVm()
        manager = RealTimeAnalysisWindowManager(
            analysis_vm=analysis_vm,
            dbc_manager=object(),
            time_config_vm=_TimeConfigVm(),
            get_timezone=lambda: "none",
            is_live=lambda: False,
            data_vm=data_vm,
        )
        window = _Window()
        with patch("views.realtime_analysis_window_manager.RealTimeAnalysisWindow", return_value=window) as constructor:
            manager.open_window()
        analysis_vm.set_offline_dataframe.assert_called_once_with(data_vm.df)
        self.assertTrue(constructor.call_args.kwargs["offline_mode"])

    def test_live_transitions_switch_window_mode_and_reindex_when_stopped(self):
        analysis_vm = _AnalysisVm()
        analysis_vm.set_offline_dataframe = Mock()
        analysis_vm.set_live_mode = Mock()
        data_vm = _DataVm()
        connection_vm = _ConnectionVm()
        live = {"value": False}
        manager = RealTimeAnalysisWindowManager(
            analysis_vm=analysis_vm,
            dbc_manager=object(),
            time_config_vm=_TimeConfigVm(),
            get_timezone=lambda: "none",
            is_live=lambda: live["value"],
            data_vm=data_vm,
            connection_vm=connection_vm,
        )
        window = _Window()
        with patch("views.realtime_analysis_window_manager.RealTimeAnalysisWindow", return_value=window):
            manager.open_window()
        live["value"] = True
        connection_vm.running_changed.emit(True)
        analysis_vm.set_live_mode.assert_called_once_with()
        self.assertEqual(window.offline_modes, [False])
        live["value"] = False
        connection_vm.running_changed.emit(False)
        self.assertEqual(data_vm.flushed, 1)
        analysis_vm.set_offline_dataframe.assert_called_with(data_vm.df)
        self.assertEqual(analysis_vm.set_offline_dataframe.call_count, 2)
        self.assertEqual(window.offline_modes, [False, True])


if __name__ == "__main__":
    unittest.main()
