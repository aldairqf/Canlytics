"""Characterization tests for utils/filters.apply_filter.

Pins the current numeric behavior of each smoothing/rounding filter so the
plot pipeline can't be silently broken by a refactor.
"""

from __future__ import annotations

import unittest

import numpy as np

from utils.filters import apply_filter


class PassthroughTests(unittest.TestCase):
    def test_none_filter_returns_float_array(self):
        out = apply_filter([1, 2, 3], None, None)
        self.assertIsInstance(out, np.ndarray)
        np.testing.assert_array_equal(out, np.array([1.0, 2.0, 3.0]))

    def test_string_none_is_passthrough(self):
        np.testing.assert_array_equal(apply_filter([1, 2], "None", {}), np.array([1.0, 2.0]))

    def test_unknown_filter_is_passthrough(self):
        np.testing.assert_array_equal(apply_filter([1, 2], "Nope", {}), np.array([1.0, 2.0]))


class MovingAverageTests(unittest.TestCase):
    def test_constant_signal_is_preserved(self):
        out = apply_filter([5, 5, 5, 5], "Moving Average", {"window": 3})
        np.testing.assert_allclose(out, [5, 5, 5, 5])

    def test_length_is_preserved(self):
        out = apply_filter([0, 1, 2, 3, 4], "Moving Average", {"window": 3})
        self.assertEqual(len(out), 5)

    def test_window_one_is_passthrough(self):
        out = apply_filter([0, 1, 2], "Moving Average", {"window": 1})
        np.testing.assert_array_equal(out, [0, 1, 2])

    def test_even_window_is_bumped_odd(self):
        # window 2 -> 3; constant stays constant, length preserved
        out = apply_filter([2, 2, 2], "Moving Average", {"window": 2})
        self.assertEqual(len(out), 3)
        np.testing.assert_allclose(out, [2, 2, 2])


class ExponentialMovingAverageTests(unittest.TestCase):
    def test_first_value_equals_input(self):
        out = apply_filter([10, 20, 30], "Exponential Moving Average", {"alpha": 0.5})
        self.assertEqual(out[0], 10.0)

    def test_recurrence(self):
        # out[i] = alpha*y[i] + (1-alpha)*out[i-1]
        out = apply_filter([0, 10], "Exponential Moving Average", {"alpha": 0.2})
        self.assertAlmostEqual(out[1], 0.2 * 10 + 0.8 * 0)

    def test_empty_input(self):
        out = apply_filter([], "Exponential Moving Average", {"alpha": 0.2})
        self.assertEqual(len(out), 0)


class MedianTests(unittest.TestCase):
    def test_removes_single_spike(self):
        out = apply_filter([1, 1, 100, 1, 1], "Median", {"window": 3})
        np.testing.assert_allclose(out, [1, 1, 1, 1, 1])

    def test_window_one_passthrough(self):
        np.testing.assert_array_equal(
            apply_filter([1, 2, 3], "Median", {"window": 1}), [1, 2, 3]
        )


class GaussianTests(unittest.TestCase):
    def test_constant_preserved_and_length(self):
        out = apply_filter([4, 4, 4, 4], "Gaussian", {"sigma": 1.0})
        self.assertEqual(len(out), 4)
        np.testing.assert_allclose(out, [4, 4, 4, 4])

    def test_non_positive_sigma_passthrough(self):
        np.testing.assert_array_equal(
            apply_filter([1, 2, 3], "Gaussian", {"sigma": 0}), [1, 2, 3]
        )


class SavitzkyGolayTests(unittest.TestCase):
    def test_window_not_greater_than_polyorder_passthrough(self):
        out = apply_filter([1, 2, 3], "Savitzky-Golay", {"window": 2, "polyorder": 2})
        np.testing.assert_array_equal(out, [1, 2, 3])

    def test_fits_linear_trend_exactly(self):
        # A degree-2 fit reproduces a straight line.
        out = apply_filter([0, 1, 2, 3, 4], "Savitzky-Golay", {"window": 3, "polyorder": 2})
        np.testing.assert_allclose(out, [0, 1, 2, 3, 4], atol=1e-9)


class RoundingTests(unittest.TestCase):
    def test_truncate_decimals(self):
        out = apply_filter([1.279, 2.999], "Truncate Decimals", {"decimals": 1})
        np.testing.assert_allclose(out, [1.2, 2.9])

    def test_round_decimals(self):
        out = apply_filter([1.279, 2.949], "Round Decimals", {"decimals": 1})
        np.testing.assert_allclose(out, [1.3, 2.9])

    def test_negative_decimals_clamped_to_zero(self):
        out = apply_filter([1.7, 2.2], "Round Decimals", {"decimals": -3})
        np.testing.assert_allclose(out, [2.0, 2.0])


if __name__ == "__main__":
    unittest.main()
