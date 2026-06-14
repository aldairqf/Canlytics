"""Characterization tests for utils/plot_sampling.downsample_series."""

from __future__ import annotations

import unittest

from utils.plot_sampling import downsample_series


class DownsampleSeriesTests(unittest.TestCase):
    def test_non_positive_max_points_returns_input(self):
        x = [0, 1, 2]
        y = [10, 11, 12]
        self.assertEqual(downsample_series(x, y, 0), (x, y))
        self.assertEqual(downsample_series(x, y, -5), (x, y))

    def test_under_budget_returns_input_unchanged(self):
        x = [0, 1, 2]
        y = [10, 11, 12]
        rx, ry = downsample_series(x, y, 3)
        self.assertEqual(rx, x)
        self.assertEqual(ry, y)

    def test_downsamples_with_ceil_step(self):
        x = list(range(10))
        y = list(range(100, 110))
        # step = ceil(10 / 3) = 4 -> indexes 0, 4, 8
        rx, ry = downsample_series(x, y, 3)
        self.assertEqual(list(rx), [0, 4, 8])
        self.assertEqual(list(ry), [100, 104, 108])

    def test_step_one_when_just_over_budget(self):
        x = list(range(5))
        y = list(range(5))
        # len 5, max 4 -> step = ceil(5/4) = 2 -> indexes 0,2,4
        rx, ry = downsample_series(x, y, 4)
        self.assertEqual(list(rx), [0, 2, 4])


if __name__ == "__main__":
    unittest.main()
