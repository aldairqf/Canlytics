from __future__ import annotations

import tempfile
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


if __name__ == "__main__":
    unittest.main()
