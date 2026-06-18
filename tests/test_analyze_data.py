"""Characterization tests for services/analyze_data.py.

Covers the pure analysis helpers that were extracted from AnalyzeDataViewModel:
sorted_can_ids, detect_mux_cases, build_summary, build_plot_series,
shannon_entropy, and update_periods.
"""

from __future__ import annotations

import unittest

import polars as pl

from services.analyze_data import (
    ByteSeries,
    build_plot_series,
    build_summary,
    detect_mux_cases,
    shannon_entropy,
    sorted_can_ids,
    update_periods,
)


class SortedCanIdsTests(unittest.TestCase):
    def test_empty_dataframe_returns_empty(self):
        self.assertEqual(sorted_can_ids(pl.DataFrame()), [])

    def test_none_returns_empty(self):
        self.assertEqual(sorted_can_ids(None), [])  # type: ignore[arg-type]

    def test_sorts_numerically(self):
        df = pl.DataFrame({"ID": ["00000200", "00000100", "00000300"]})
        self.assertEqual(sorted_can_ids(df), ["00000100", "00000200", "00000300"])

    def test_deduplicates(self):
        df = pl.DataFrame({"ID": ["00000100", "00000100", "00000200"]})
        result = sorted_can_ids(df)
        self.assertEqual(result.count("00000100"), 1)


class DetectMuxCasesTests(unittest.TestCase):
    def _df(self, b0_values: list[str]) -> pl.DataFrame:
        return pl.DataFrame({"B0": b0_values, "B1": ["00"] * len(b0_values)})

    def test_empty_df_returns_empty(self):
        self.assertEqual(detect_mux_cases(pl.DataFrame(), (0,)), [])

    def test_empty_mux_bytes_returns_empty(self):
        self.assertEqual(detect_mux_cases(self._df(["FF"]), ()), [])

    def test_single_mux_byte(self):
        df = pl.DataFrame({"B0": ["FF", "00", "FF", "01"]})
        cases = detect_mux_cases(df, (0,))
        self.assertIn("FF", cases)
        self.assertIn("00", cases)
        self.assertIn("01", cases)

    def test_preserves_first_occurrence_order(self):
        df = pl.DataFrame({"B0": ["AA", "BB", "AA", "CC"]})
        cases = detect_mux_cases(df, (0,))
        self.assertEqual(cases, ["AA", "BB", "CC"])

    def test_two_mux_bytes_concatenated_with_space(self):
        df = pl.DataFrame({"B0": ["FF", "00"], "B1": ["01", "02"]})
        cases = detect_mux_cases(df, (0, 1))
        self.assertIn("FF 01", cases)
        self.assertIn("00 02", cases)


class BuildSummaryTests(unittest.TestCase):
    def _simple_df(self) -> pl.DataFrame:
        return pl.DataFrame({
            "TS": [0.0, 0.01, 0.02, 0.03],
            "ID": ["00000100"] * 4,
            "LEN": [3, 3, 3, 3],
            "DATA": ["FF0011", "FF0022", "FF0011", "FF0033"],
            "B0": ["FF", "FF", "FF", "FF"],
            "B1": ["00", "00", "00", "00"],
            "B2": ["11", "22", "11", "33"],
            "D0": [255, 255, 255, 255],
            "D1": [0, 0, 0, 0],
            "D2": [17, 34, 17, 51],
        })

    def test_empty_df_returns_zero_frames(self):
        result = build_summary(pl.DataFrame(), "00000100", (), "All")
        self.assertEqual(result["Frames"], 0)

    def test_frame_count(self):
        result = build_summary(self._simple_df(), "00000100", (), "All")
        self.assertEqual(result["Frames"], 4)

    def test_mean_period(self):
        result = build_summary(self._simple_df(), "00000100", (), "All")
        self.assertAlmostEqual(float(result["Mean Period"]), 0.01, places=5)

    def test_payload_changes_detected(self):
        result = build_summary(self._simple_df(), "00000100", (), "All")
        self.assertGreater(result["Payload Changes"], 0)

    def test_constant_byte_has_zero_changes(self):
        result = build_summary(self._simple_df(), "00000100", (), "All")
        # B0 is always FF — changes should be 0
        self.assertIn("B0:0", result["Byte Changes"])

    def test_distinct_payloads(self):
        result = build_summary(self._simple_df(), "00000100", (), "All")
        # FF0011, FF0022, FF0033 → 3 distinct
        self.assertEqual(result["Distinct Payloads"], 3)


class BuildPlotSeriesTests(unittest.TestCase):
    def _df(self) -> pl.DataFrame:
        return pl.DataFrame({
            "TS": [0.0, 1.0, 2.0],
            "D0": [10, 20, 30],
            "D1": [1, 2, 3],
        })

    def test_empty_df_returns_empty(self):
        self.assertEqual(build_plot_series(pl.DataFrame(), {0}), [])

    def test_no_selected_bytes_returns_empty(self):
        self.assertEqual(build_plot_series(self._df(), set()), [])

    def test_returns_one_series_per_selected_byte(self):
        result = build_plot_series(self._df(), {0, 1})
        self.assertEqual(len(result), 2)

    def test_series_values_match_column(self):
        result = build_plot_series(self._df(), {0})
        self.assertEqual(result[0].y, [10, 20, 30])

    def test_series_label(self):
        result = build_plot_series(self._df(), {0})
        self.assertEqual(result[0].label, "B0")

    def test_byte_series_is_frozen_dataclass(self):
        s = ByteSeries(label="B0", x=[0.0], y=[1], color="#fff")
        with self.assertRaises(Exception):
            s.label = "B1"  # type: ignore[misc]


class ShannonEntropyTests(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(shannon_entropy([]), 0.0)

    def test_uniform_single_value_is_zero(self):
        self.assertAlmostEqual(shannon_entropy(["FF", "FF", "FF"]), 0.0)

    def test_two_equal_values_is_one_bit(self):
        self.assertAlmostEqual(shannon_entropy(["00", "FF", "00", "FF"]), 1.0, places=10)

    def test_more_diverse_is_higher(self):
        low = shannon_entropy(["AA", "AA", "AA", "BB"])
        high = shannon_entropy(["AA", "BB", "CC", "DD"])
        self.assertGreater(high, low)


class UpdatePeriodsTests(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(update_periods([], []), [])

    def test_no_changes_returns_empty(self):
        self.assertEqual(update_periods([0.0, 1.0, 2.0], ["FF", "FF", "FF"]), [])

    def test_single_change_returns_empty(self):
        # Need at least two changes to compute a period between them
        self.assertEqual(update_periods([0.0, 1.0, 2.0], ["FF", "00", "00"]), [])

    def test_two_changes_returns_one_period(self):
        result = update_periods([0.0, 1.0, 3.0], ["FF", "00", "FF"])
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0], 2.0, places=5)

    def test_mismatched_lengths_returns_empty(self):
        self.assertEqual(update_periods([0.0, 1.0], ["FF"]), [])


if __name__ == "__main__":
    unittest.main()
