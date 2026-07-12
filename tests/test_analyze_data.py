"""Characterization tests for services/analyze_data.py.

Covers the pure analysis helpers that were extracted from AnalyzeDataViewModel:
sorted_can_ids, detect_mux_cases, build_summary, build_plot_series,
shannon_entropy, update_periods, and the incremental AnalyzeDataAccumulator.
"""

from __future__ import annotations

import random
import unittest

import polars as pl

from services.analyze_data import (
    AnalyzeDataAccumulator,
    ByteSeries,
    build_accumulator,
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


def _random_df(n: int, *, seed: int) -> pl.DataFrame:
    rng = random.Random(seed)
    ts = sorted(rng.uniform(0, 100) for _ in range(n))
    b_cols = {f"B{i}": [f"{rng.randint(0, 3):02X}" for _ in range(n)] for i in range(8)}
    d_cols = {f"D{i}": [rng.randint(0, 3) for _ in range(n)] for i in range(8)}
    data = ["".join(b_cols[f"B{i}"][row] for i in range(8)) for row in range(n)]
    return pl.DataFrame({
        "TS": ts,
        "LEN": [8] * n,
        "DATA": data,
        **b_cols,
        **d_cols,
    })


class AccumulatorMatchesFullFunctionsTests(unittest.TestCase):
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

    def test_snapshot_matches_build_summary(self):
        df = self._simple_df()
        acc = build_accumulator(df)
        self.assertEqual(acc.snapshot("00000100", (), "All"), build_summary(df, "00000100", (), "All"))

    def test_plot_series_matches_build_plot_series(self):
        df = self._simple_df()
        acc = build_accumulator(df)
        self.assertEqual(acc.plot_series({0, 1, 2}), build_plot_series(df, {0, 1, 2}))

    def test_empty_df_snapshot_matches_empty_build_summary(self):
        acc = build_accumulator(pl.DataFrame())
        self.assertEqual(acc.snapshot("00000100", (1,), "All"), build_summary(pl.DataFrame(), "00000100", (1,), "All"))

    def test_empty_df_plot_series_matches(self):
        acc = build_accumulator(pl.DataFrame())
        self.assertEqual(acc.plot_series({0}), build_plot_series(pl.DataFrame(), {0}))


class AccumulatorIncrementalEqualsFullTests(unittest.TestCase):
    def test_split_feed_matches_single_feed(self):
        df = _random_df(120, seed=1)

        full = AnalyzeDataAccumulator()
        full.feed(df)

        incremental = AnalyzeDataAccumulator()
        for start in range(0, df.height, 17):  # odd chunk size, doesn't divide evenly
            incremental.feed(df[start : start + 17])

        self.assertEqual(
            incremental.snapshot("00000100", (0,), "All"),
            full.snapshot("00000100", (0,), "All"),
        )
        self.assertEqual(incremental.plot_series(set(range(8))), full.plot_series(set(range(8))))

    def test_many_single_row_feeds_match_single_feed(self):
        df = _random_df(40, seed=2)

        full = AnalyzeDataAccumulator()
        full.feed(df)

        incremental = AnalyzeDataAccumulator()
        for row in range(df.height):
            incremental.feed(df[row : row + 1])

        self.assertEqual(
            incremental.snapshot("00000200", (), "All"),
            full.snapshot("00000200", (), "All"),
        )
        self.assertEqual(incremental.plot_series({0, 3, 7}), full.plot_series({0, 3, 7}))

    def test_feed_is_order_independent_of_call_boundaries_not_row_order(self):
        # Splitting a sorted df at arbitrary points must give the same result.
        df = _random_df(75, seed=3)
        full = AnalyzeDataAccumulator()
        full.feed(df)

        for chunk_size in (1, 3, 10, 37, 75):
            incremental = AnalyzeDataAccumulator()
            for start in range(0, df.height, chunk_size):
                incremental.feed(df[start : start + chunk_size])
            self.assertEqual(
                incremental.snapshot("X", (), "All"),
                full.snapshot("X", (), "All"),
                f"mismatch at chunk_size={chunk_size}",
            )


class BuildAccumulatorTests(unittest.TestCase):
    def test_returns_accumulator_seeded_from_df(self):
        df = pl.DataFrame({"TS": [0.0, 1.0], "DATA": ["AA", "BB"], "B0": ["AA", "BB"], "D0": [1, 2]})
        acc = build_accumulator(df)
        self.assertIsInstance(acc, AnalyzeDataAccumulator)
        self.assertEqual(acc.snapshot(None, (), "All")["Frames"], 2)


if __name__ == "__main__":
    unittest.main()
