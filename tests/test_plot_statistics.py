from __future__ import annotations

import unittest

import numpy as np

from utils.plot_statistics import interval_statistics


class IntervalStatisticsTests(unittest.TestCase):
    def test_includes_both_cursor_endpoints(self) -> None:
        result = interval_statistics(
            np.array([0.0, 1.0, 2.0, 3.0]),
            np.array([9.0, 2.0, 4.0, 8.0]),
            1.0,
            2.0,
        )
        self.assertEqual(result, (2, 3.0, 2.0, 4.0))

    def test_accepts_reversed_cursor_order(self) -> None:
        result = interval_statistics(np.arange(4.0), np.array([1.0, 3.0, 5.0, 7.0]), 3.0, 1.0)
        self.assertEqual(result, (3, 5.0, 3.0, 7.0))

    def test_empty_interval_returns_no_statistics(self) -> None:
        result = interval_statistics(np.array([0.0, 2.0]), np.array([1.0, 3.0]), 0.5, 1.5)
        self.assertEqual(result, (0, None, None, None))

    def test_ignores_non_finite_values(self) -> None:
        result = interval_statistics(np.arange(3.0), np.array([2.0, np.nan, 6.0]), 0.0, 2.0)
        self.assertEqual(result, (2, 4.0, 2.0, 6.0))

    def test_rejects_mismatched_series(self) -> None:
        with self.assertRaises(ValueError):
            interval_statistics(np.array([0.0]), np.array([1.0, 2.0]), 0.0, 1.0)


if __name__ == "__main__":
    unittest.main()
