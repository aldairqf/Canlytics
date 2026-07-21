"""Characterization tests for utils/plot_sampling.downsample_series."""

from __future__ import annotations

import unittest

from utils.plot_sampling import downsample_series, minmax_downsample


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


class MinmaxDownsampleTests(unittest.TestCase):
    """minmax_downsample() must never lose a single-frame spike, unlike naive stride sampling."""

    def test_non_positive_max_points_returns_input(self):
        x = [0, 1, 2]
        y = [10, 11, 12]
        rx, ry = minmax_downsample(x, y, 0)
        self.assertEqual(list(rx), x)
        self.assertEqual(list(ry), y)

    def test_under_budget_returns_input_unchanged(self):
        x = [0, 1, 2]
        y = [10, 11, 12]
        rx, ry = minmax_downsample(x, y, 3)
        self.assertEqual(list(rx), x)
        self.assertEqual(list(ry), y)

    def test_a_single_frame_spike_survives_heavy_decimation(self):
        n = 10_000
        y = [0] * n
        spike_index = 4321
        y[spike_index] = 999
        x = list(range(n))
        rx, ry = minmax_downsample(x, y, 150)
        self.assertIn(999, list(ry))
        self.assertLessEqual(len(rx), 150 + 1)  # allow +1 for the last partial bucket

    def test_min_and_max_both_kept_per_bucket(self):
        # One bucket (n <= bucket_size) containing both a dip and a peak.
        y = [5, 5, -3, 5, 5, 40, 5, 5]
        x = list(range(len(y)))
        rx, ry = minmax_downsample(x, y, 2)
        self.assertIn(-3, list(ry))
        self.assertIn(40, list(ry))

    def test_output_stays_in_chronological_order_within_each_bucket(self):
        y = [5, 40, 5, -3, 5]  # max before min within the same bucket
        x = list(range(len(y)))
        rx, ry = minmax_downsample(x, y, 2)
        self.assertEqual(list(rx), sorted(rx))


if __name__ == "__main__":
    unittest.main()
