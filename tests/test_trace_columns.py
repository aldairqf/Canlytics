from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from services.trace_columns import (
    calculate_appended_delta_t,
    calculate_delta_t,
    normalize_trace_preferences,
)
from services.session_state import SessionStateStore


class TraceColumnTests(unittest.TestCase):
    def test_delta_t_uses_previous_timestamp_per_id_and_restores_source_order(self):
        dataframe = pl.DataFrame(
            {"TS": [1.0, 2.0, 3.0, 5.0], "ID": ["100", "200", "100", "100"]}
        )

        self.assertEqual(calculate_delta_t(dataframe), [None, None, 2.0, 2.0])

    def test_delta_t_uses_source_order_when_timestamps_are_reordered(self):
        dataframe = pl.DataFrame({"TS": [3.0, 1.0, 2.0], "ID": ["100"] * 3})

        self.assertEqual(calculate_delta_t(dataframe), [None, -2.0, 1.0])

    def test_append_delta_t_is_incremental_by_id(self):
        dataframe = pl.DataFrame({"TS": [4.0, 7.0, 8.0], "ID": ["100", "200", "100"]})

        deltas, last = calculate_appended_delta_t(dataframe, {"100": 2.0})

        self.assertEqual(deltas, [2.0, None, 4.0])
        self.assertEqual(last, {"100": 8.0, "200": 7.0})

    def test_missing_timestamp_columns_returns_null_values(self):
        self.assertEqual(calculate_delta_t(pl.DataFrame({"ID": ["100"]})), [None])

    def test_invalid_preferences_fall_back_to_safe_defaults(self):
        self.assertEqual(
            normalize_trace_preferences({"data_mode": "bad", "show_name": "false"}),
            {"data_mode": "hex", "show_delta_t": False, "show_name": False},
        )

    def test_trace_preferences_round_trip_through_session_state(self):
        expected = {"data_mode": "bits", "show_delta_t": True, "show_name": False}
        with TemporaryDirectory() as directory:
            store = SessionStateStore(Path(directory))
            store.set_window_prefs("main_trace", expected)

            actual = normalize_trace_preferences(store.get_window_prefs("main_trace"))

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
