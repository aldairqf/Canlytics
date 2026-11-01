from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal

from views.analyze_data_window_manager import AnalyzeDataWindowManager


class _DataVm(QObject):
    dataframe_changed = Signal(object)
    dataframe_replaced = Signal(object)

    def __init__(self, df):
        super().__init__()
        self.df = df


class _ConnectionVm(QObject):
    chunk_ready = Signal(object)


class _AnalyzeVm:
    def __init__(self):
        self.calls = []

    def reset_dataframe(self, df):
        self.calls.append(("reset", df))

    def set_dataframe(self, df):
        self.calls.append(("set", df))

    def ingest_raw_chunk(self, chunk):
        self.calls.append(("chunk", chunk))


class _Window(QObject):
    destroyed = Signal(object)

    def show(self):
        pass

    def raise_(self):
        pass

    def activateWindow(self):
        pass


class AnalyzeDataWindowManagerTests(unittest.TestCase):
    def setUp(self):
        self.df = object()
        self.chunk = object()
        self.data_vm = _DataVm(self.df)
        self.connection_vm = _ConnectionVm()
        self.vm = _AnalyzeVm()
        self.manager = AnalyzeDataWindowManager(
            vm=self.vm,
            data_vm=self.data_vm,
            connection_vm=self.connection_vm,
            time_config_vm=None,
            get_timezone=lambda: "none",
        )

    def test_updates_are_ignored_until_window_opens_then_stream_live(self):
        self.data_vm.dataframe_changed.emit(self.df)
        self.connection_vm.chunk_ready.emit(self.chunk)
        self.assertEqual(self.vm.calls, [])

        with patch("views.analyze_data_window_manager.AnalyzeDataWindow", return_value=_Window()):
            self.manager.open_window()

        self.assertEqual(self.vm.calls, [("reset", self.df), ("set", self.df)])
        self.data_vm.dataframe_changed.emit(self.df)
        self.data_vm.dataframe_replaced.emit(self.df)
        self.connection_vm.chunk_ready.emit(self.chunk)
        self.assertEqual(
            self.vm.calls,
            [("reset", self.df), ("set", self.df), ("set", self.df), ("reset", self.df), ("chunk", self.chunk)],
        )

    def test_window_destruction_disconnects_and_releases_analysis_state(self):
        with patch("views.analyze_data_window_manager.AnalyzeDataWindow", return_value=_Window()):
            window = self.manager.open_window()

        self.manager._on_window_destroyed(window)
        self.data_vm.dataframe_changed.emit(self.df)
        self.data_vm.dataframe_replaced.emit(self.df)
        self.connection_vm.chunk_ready.emit(self.chunk)
        self.assertEqual(
            self.vm.calls,
            [("reset", self.df), ("set", self.df), ("reset", None)],
        )

    def test_constructor_failure_does_not_connect_signals_and_reopen_connects_once(self):
        with patch(
            "views.analyze_data_window_manager.AnalyzeDataWindow",
            side_effect=[RuntimeError("construction failed"), _Window()],
        ) as constructor:
            with self.assertRaisesRegex(RuntimeError, "construction failed"):
                self.manager.open_window()

            failed_prime_calls = [("reset", self.df), ("set", self.df)]
            self.assertEqual(self.vm.calls, failed_prime_calls)
            self.data_vm.dataframe_changed.emit(self.df)
            self.data_vm.dataframe_replaced.emit(self.df)
            self.connection_vm.chunk_ready.emit(self.chunk)
            self.assertEqual(self.vm.calls, failed_prime_calls)

            window = self.manager.open_window()
            self.assertEqual(constructor.call_count, 2)

        self.assertEqual(self.vm.calls, failed_prime_calls * 2)
        self.data_vm.dataframe_changed.emit(self.df)
        self.data_vm.dataframe_replaced.emit(self.df)
        self.connection_vm.chunk_ready.emit(self.chunk)
        self.assertEqual(
            self.vm.calls,
            failed_prime_calls * 2
            + [("set", self.df), ("reset", self.df), ("chunk", self.chunk)],
        )

        self.manager._on_window_destroyed(window)


if __name__ == "__main__":
    unittest.main()
