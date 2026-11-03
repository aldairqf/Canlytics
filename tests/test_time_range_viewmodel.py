from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import polars as pl
from PySide6.QtCore import QCoreApplication

from services.session_state import SessionStateStore
from viewmodels.main_window_viewmodel import MainWindowViewModel
from viewmodels.time_range_viewmodel import TimeRangeViewModel


class TimeRangeViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_state_is_validated_copied_and_published(self) -> None:
        vm = TimeRangeViewModel()
        ranges = []
        states = []
        vm.range_changed.connect(lambda start, end: ranges.append((start, end)))
        vm.filter_state_changed.connect(states.append)
        state = {"ts_from": "1", "ts_to": "5", "date_from": "", "date_to": ""}

        vm.set_time_range(1, 5, filter_state=state)
        state["ts_from"] = "corrupted"

        self.assertEqual(ranges, [(1.0, 5.0)])
        self.assertEqual(vm.filter_state["ts_from"], "1")
        self.assertEqual(states[-1]["ts_to"], "5")
        with self.assertRaises(ValueError):
            vm.set_time_range(6, 5)
        with self.assertRaises(ValueError):
            vm.set_time_range(float("nan"), None)
        self.assertEqual(vm.time_range, (1.0, 5.0))

    def test_root_propagates_scalar_range_to_all_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SessionStateStore(root=Path(folder))
            with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
                root = MainWindowViewModel()
            try:
                root.time_range_vm.set_time_range(10, 20)
                self.assertEqual(root.filter_vm.time_range, (10.0, 20.0))
                self.assertEqual(root.analyze_data_vm._ts_min, 10.0)
                self.assertEqual(root.mux_detection_vm._ts_min, 10.0)
                self.assertEqual(root.candidate_interpretations_vm._ts_min, 10.0)
                root.candidate_interpretations_vm._df = pl.DataFrame(
                    {"TS": [1.0, 2.0, 3.0, 4.0, 5.0], "ID": ["100"] * 5}
                )
                root.candidate_interpretations_vm.set_time_ranges(((1, 2), (4, 5)))
                root.time_range_vm.set_time_range(30, 40)
                self.assertEqual(root.candidate_interpretations_vm._time_ranges, ((1.0, 2.0), (4.0, 5.0)))
                self.assertEqual(
                    root.candidate_interpretations_vm._effective_df()["TS"].to_list(),
                    [1.0, 2.0, 4.0, 5.0],
                )
                root.candidate_interpretations_vm.set_time_ranges(())
                self.assertEqual(root.candidate_interpretations_vm._effective_df().height, 0)
                self.assertEqual(root.time_range_vm.time_range, (30.0, 40.0))
            finally:
                root.shutdown()

    def test_root_shutdown_stops_candidate_interpretations_viewmodel(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SessionStateStore(root=Path(folder))
            with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
                root = MainWindowViewModel()
            with patch.object(root.candidate_interpretations_vm, "shutdown", wraps=root.candidate_interpretations_vm.shutdown) as stop:
                root.shutdown()
            stop.assert_called_once_with()

    def test_normalize_failure_restores_previous_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SessionStateStore(root=Path(folder))
            with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
                root = MainWindowViewModel()
            try:
                fixture = Path(__file__).resolve().parent / "fixtures" / "logs" / "candump-sample.log"
                root.data_vm.load_log(str(fixture))
                root.time_config_vm.apply(normalize=False, timezone="UTC")

                def fail_load(_normalize=False):
                    raise OSError("read failed")

                root.data_vm._log.load = fail_load
                failures = []
                root.normalize_failed.connect(failures.append)
                root.time_config_vm.apply(normalize=True, timezone="UTC")

                deadline = time.monotonic() + 3.0
                while not failures and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.app.processEvents()

                self.assertTrue(failures)
                self.assertFalse(root.time_config_vm.normalize)
                self.assertEqual(root.time_config_vm.timezone, "UTC")
            finally:
                root.shutdown()

    def test_canceling_normalize_restores_timezone_before_worker_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SessionStateStore(root=Path(folder))
            with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
                root = MainWindowViewModel()
            try:
                fixture = Path(__file__).resolve().parent / "fixtures" / "logs" / "candump-sample.log"
                root.data_vm.load_log(str(fixture))
                root.time_config_vm.apply(normalize=False, timezone="UTC")
                started = threading.Event()
                release = threading.Event()
                original_load = root.data_vm._log.load

                def delayed_load(normalize=False):
                    started.set()
                    release.wait(2.0)
                    return original_load(normalize)

                root.data_vm._log.load = delayed_load
                root.time_config_vm.apply(normalize=True, timezone="UTC")
                deadline = time.monotonic() + 3.0
                while not started.is_set() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertTrue(started.is_set())

                root.time_config_vm.apply(normalize=False, timezone="none")
                self.assertFalse(root.time_config_vm.normalize)
                self.assertEqual(root.time_config_vm.timezone, "UTC")
                release.set()
                deadline = time.monotonic() + 3.0
                while root.data_vm._normalize_worker is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.app.processEvents()
                self.assertIsNone(root.data_vm._normalize_worker)
                self.assertEqual(root.data_vm.df["TS"][0], 1779067270.672182)
            finally:
                release.set()
                root.shutdown()

    def test_canceling_normalize_preserves_explicit_new_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SessionStateStore(root=Path(folder))
            with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
                root = MainWindowViewModel()
            release = threading.Event()
            try:
                fixture = Path(__file__).resolve().parent / "fixtures" / "logs" / "candump-sample.log"
                root.data_vm.load_log(str(fixture))
                root.time_config_vm.apply(normalize=False, timezone="UTC")
                started = threading.Event()
                original_load = root.data_vm._log.load

                def delayed_load(normalize=False):
                    started.set()
                    release.wait(2.0)
                    return original_load(normalize)

                root.data_vm._log.load = delayed_load
                root.time_config_vm.apply(normalize=True, timezone="UTC")
                deadline = time.monotonic() + 3.0
                while not started.is_set() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertTrue(started.is_set())

                root.time_config_vm.apply(normalize=False, timezone="America/New_York")
                self.assertFalse(root.time_config_vm.normalize)
                self.assertEqual(root.time_config_vm.timezone, "America/New_York")
                release.set()
                deadline = time.monotonic() + 3.0
                while root.data_vm._normalize_worker is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.app.processEvents()
                self.assertEqual(root.time_config_vm.timezone, "America/New_York")
            finally:
                release.set()
                root.shutdown()


if __name__ == "__main__":
    unittest.main()
