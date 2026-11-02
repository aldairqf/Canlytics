from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from services.xy_plot import align_xy_series, export_xy_csv


class AlignXySeriesTests(unittest.TestCase):
    def test_uses_latest_y_at_or_before_each_x_timestamp(self):
        ts, x, y = align_xy_series(
            np.array([3.0, 1.0, 2.0]), np.array([30.0, 10.0, 20.0]),
            np.array([0.0, 1.5, 2.5]), np.array([4.0, 5.0, 6.0]),
        )
        np.testing.assert_array_equal(ts, [1.0, 2.0, 3.0])
        np.testing.assert_array_equal(x, [10.0, 20.0, 30.0])
        np.testing.assert_array_equal(y, [4.0, 5.0, 6.0])

    def test_range_filters_x_and_drops_x_without_prior_y(self):
        ts, x, y = align_xy_series(
            np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0, 30.0]),
            np.array([1.5, 2.5]), np.array([15.0, 25.0]), start=2.0, end=3.0,
        )
        np.testing.assert_array_equal(ts, [2.0, 3.0])
        np.testing.assert_array_equal(x, [20.0, 30.0])
        np.testing.assert_array_equal(y, [15.0, 25.0])

    def test_empty_y_returns_empty_aligned_series(self):
        result = align_xy_series(np.array([1.0]), np.array([2.0]), np.array([]), np.array([]))
        self.assertTrue(all(values.size == 0 for values in result))

    def test_rejects_mismatched_timestamps_and_values(self):
        with self.assertRaises(ValueError):
            align_xy_series(np.array([1.0]), np.array([]), np.array([]), np.array([]))

    def test_export_writes_timestamps_and_named_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "xy.csv"
            export_xy_csv(
                path, np.array([1.0]), np.array([2.0]), np.array([3.0]),
                x_name="speed", y_name="rpm",
            )
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
        self.assertEqual(rows, [["Timestamp (epoch seconds)", "speed", "rpm"], ["1.0", "2.0", "3.0"]])
