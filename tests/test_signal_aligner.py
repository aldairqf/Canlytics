"""Characterization tests for services/signal_aligner.py."""

from __future__ import annotations

import math
import unittest

import numpy as np

from services.signal_aligner import align


class AlignEmptyTests(unittest.TestCase):
    def test_no_series_returns_empty(self):
        ts, aligned = align()
        self.assertEqual(len(ts), 0)
        self.assertEqual(aligned, [])

    def test_single_empty_series(self):
        ts, aligned = align((np.array([]), np.array([])))
        self.assertEqual(len(ts), 0)
        self.assertEqual(len(aligned), 1)

    def test_single_series_is_identity(self):
        t = np.array([1.0, 2.0, 3.0])
        y = np.array([10.0, 20.0, 30.0])
        common_ts, (out,) = align((t, y))
        np.testing.assert_array_equal(common_ts, t)
        np.testing.assert_array_equal(out, y)


class AlignForwardFillTests(unittest.TestCase):
    def test_two_same_timestamps(self):
        t = np.array([1.0, 2.0, 3.0])
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([10.0, 20.0, 30.0])
        common_ts, (ra, rb) = align((t, a), (t, b))
        np.testing.assert_array_equal(common_ts, t)
        np.testing.assert_array_equal(ra, a)
        np.testing.assert_array_equal(rb, b)

    def test_interleaved_timestamps_forward_fill(self):
        # Series A has samples at 1, 3; series B at 2, 4
        ts_a = np.array([1.0, 3.0])
        y_a = np.array([100.0, 300.0])
        ts_b = np.array([2.0, 4.0])
        y_b = np.array([200.0, 400.0])

        common_ts, (ra, rb) = align((ts_a, y_a), (ts_b, y_b))

        self.assertEqual(list(common_ts), [1.0, 2.0, 3.0, 4.0])
        # A at t=2: forward-fill from t=1 → 100
        self.assertEqual(ra[1], 100.0)
        # A at t=4: forward-fill from t=3 → 300
        self.assertEqual(ra[3], 300.0)
        # B at t=1: before first sample → NaN
        self.assertTrue(math.isnan(rb[0]))
        # B at t=3: forward-fill from t=2 → 200
        self.assertEqual(rb[2], 200.0)

    def test_before_first_sample_is_nan(self):
        ts_a = np.array([5.0, 10.0])
        y_a = np.array([1.0, 2.0])
        ts_b = np.array([1.0, 3.0])
        y_b = np.array([99.0, 88.0])

        common_ts, (ra, rb) = align((ts_a, y_a), (ts_b, y_b))

        # At t=1 and t=3, series A hasn't started yet
        self.assertTrue(math.isnan(ra[0]))  # t=1
        self.assertTrue(math.isnan(ra[1]))  # t=3
        # At t=5 and t=10, series B is forward-filled from t=3
        self.assertEqual(rb[2], 88.0)  # t=5 → ffill from 3
        self.assertEqual(rb[3], 88.0)  # t=10 → ffill from 3


class AlignCommonAxisTests(unittest.TestCase):
    def test_union_of_timestamps(self):
        ts_a = np.array([1.0, 2.0])
        ts_b = np.array([2.0, 3.0])
        common_ts, _ = align((ts_a, np.zeros(2)), (ts_b, np.zeros(2)))
        self.assertEqual(list(common_ts), [1.0, 2.0, 3.0])

    def test_duplicate_timestamps_deduplicated(self):
        ts_a = np.array([1.0, 2.0, 2.0])
        y_a = np.array([1.0, 2.0, 3.0])
        common_ts, _ = align((ts_a, y_a))
        # np.unique deduplicates
        self.assertEqual(len(common_ts), len(np.unique(ts_a)))


if __name__ == "__main__":
    unittest.main()
