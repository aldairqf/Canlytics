from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal

from views.realtime_analysis_window_manager import RealTimeAnalysisWindowManager


class _AnalysisVm:
    def __init__(self):
        self.enabled = []

    def set_enabled(self, enabled):
        self.enabled.append(enabled)


class _TimeConfigVm(QObject):
    timezone_changed = Signal(str)


class _Window(QObject):
    destroyed = Signal(object)

    def show(self):
        pass

    def raise_(self):
        pass

    def activateWindow(self):
        pass


class RealTimeAnalysisWindowManagerTests(unittest.TestCase):
    def test_passes_timezone_configuration_to_window(self):
        analysis_vm = _AnalysisVm()
        time_vm = _TimeConfigVm()
        manager = RealTimeAnalysisWindowManager(
            analysis_vm=analysis_vm,
            dbc_manager=object(),
            time_config_vm=time_vm,
            get_timezone=lambda: "America/Lima",
        )
        window = _Window()

        with patch(
            "views.realtime_analysis_window_manager.RealTimeAnalysisWindow",
            return_value=window,
        ) as constructor:
            manager.open_window()

        self.assertIs(constructor.call_args.kwargs["time_config_vm"], time_vm)
        self.assertEqual(constructor.call_args.kwargs["timezone_mode"], "America/Lima")


if __name__ == "__main__":
    unittest.main()
