"""Characterization tests for services/analyze_data.py.

Covers the pure analysis helpers that were extracted from AnalyzeDataViewModel:
sorted_can_ids, detect_mux_cases, build_summary, build_plot_series,
shannon_entropy, update_periods, and the incremental AnalyzeDataAccumulator.
"""

from __future__ import annotations

import random
import unittest

import polars as pl

from models.mux_config import MuxConfigEntry
from services.analyze_data import (
    AnalyzeDataAccumulator,
    AnalyzeDataPrecomputeCanceled,
    ByteSeries,
    MatrixEntry,
    build_accumulator,
    build_all_accumulators,
    build_matrix_entries_for_id,
    build_matrix_summary,
    build_plot_series,
    build_summary,
    detect_mux_cases,
    mux_bytes_for_can_id,
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
    def _df(self, d0_values: list[int]) -> pl.DataFrame:
        return pl.DataFrame({"D0": d0_values, "D1": [0] * len(d0_values)})

    def test_empty_df_returns_empty(self):
        self.assertEqual(detect_mux_cases(pl.DataFrame(), (0,)), [])

    def test_empty_mux_bytes_returns_empty(self):
        self.assertEqual(detect_mux_cases(self._df([0xFF]), ()), [])

    def test_single_mux_byte(self):
        df = pl.DataFrame({"D0": [0xFF, 0x00, 0xFF, 0x01]})
        cases = detect_mux_cases(df, (0,))
        self.assertIn("FF", cases)
        self.assertIn("00", cases)
        self.assertIn("01", cases)

    def test_preserves_first_occurrence_order(self):
        df = pl.DataFrame({"D0": [0xAA, 0xBB, 0xAA, 0xCC]})
        cases = detect_mux_cases(df, (0,))
        self.assertEqual(cases, ["AA", "BB", "CC"])

    def test_two_mux_bytes_concatenated_with_space(self):
        df = pl.DataFrame({"D0": [0xFF, 0x00], "D1": [0x01, 0x02]})
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
    d_cols = {f"D{i}": [rng.randint(0, 3) for _ in range(n)] for i in range(8)}
    data = ["".join(f"{d_cols[f'D{i}'][row]:02X}" for i in range(8)) for row in range(n)]
    return pl.DataFrame({
        "TS": ts,
        "LEN": [8] * n,
        "DATA": data,
        **d_cols,
    })


class AccumulatorMatchesFullFunctionsTests(unittest.TestCase):
    def _simple_df(self) -> pl.DataFrame:
        return pl.DataFrame({
            "TS": [0.0, 0.01, 0.02, 0.03],
            "ID": ["00000100"] * 4,
            "LEN": [3, 3, 3, 3],
            "DATA": ["FF0011", "FF0022", "FF0011", "FF0033"],
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


class PlotSeriesCacheTests(unittest.TestCase):
    """plot_series() is called on every CAN-ID switch in the window, not just once
    per feed() -- it must reuse a cached numpy view instead of re-copying the whole
    history into fresh Python lists every time (that re-copy was the reason
    switching between already-visited signals felt slow, even after feed() itself
    was vectorized)."""

    def _df(self, n: int) -> pl.DataFrame:
        return pl.DataFrame({
            "TS": [float(i) for i in range(n)],
            "ID": ["00000100"] * n,
            "LEN": [1] * n,
            "DATA": [f"{i % 5:02X}" for i in range(n)],
            "D0": [i % 5 for i in range(n)],
        })

    def test_repeated_calls_return_the_same_cached_array_object(self):
        acc = build_accumulator(self._df(20))
        first = acc.plot_series({0})
        second = acc.plot_series({0})
        self.assertIs(first[0].x, second[0].x)
        self.assertIs(first[0].y, second[0].y)

    def test_feed_invalidates_the_cache(self):
        acc = build_accumulator(self._df(20))
        first = acc.plot_series({0})
        acc.feed(self._df(1))
        second = acc.plot_series({0})
        self.assertIsNot(first[0].x, second[0].x)
        self.assertEqual(len(second[0].x), 21)

    def test_warm_plot_series_cache_matches_lazy_result(self):
        df = self._df(15)
        warmed = build_accumulator(df)
        warmed.warm_plot_series_cache()
        lazy = build_accumulator(df)
        self.assertEqual(warmed.plot_series(set(range(8))), lazy.plot_series(set(range(8))))
        # warming already built the array -- plot_series() just returns the cached one.
        self.assertIsNotNone(warmed._ts_series_arr)


class MatrixSummaryTests(unittest.TestCase):
    """The Matrix rollup is a cheap, independent pass over the raw df -- it must
    never require building a full per-ID AnalyzeDataAccumulator."""

    def _df(self, can_id: str, b0_values: list[int], b1_values: list[int] | None = None) -> pl.DataFrame:
        n = len(b0_values)
        b1_values = b1_values if b1_values is not None else [9] * n
        return pl.DataFrame({
            "TS": [float(i) for i in range(n)],
            "ID": [can_id] * n,
            "LEN": [2] * n,
            "DATA": [f"{a:02X}{b:02X}" for a, b in zip(b0_values, b1_values)],
            "D0": b0_values,
            "D1": b1_values,
        })

    def test_returns_one_entry_per_present_byte_with_movement_flags(self):
        # Every present byte must be returned, correctly flagged -- no auto-picking.
        df = self._df("00000100", [1, 1, 1, 1], [1, 2, 3, 4])
        entries = build_matrix_summary(df, ["00000100"])
        self.assertEqual(len(entries), 2)
        by_byte = {e.byte_index: e for e in entries}
        self.assertIsInstance(by_byte[0], MatrixEntry)
        self.assertEqual(by_byte[0].can_id, "00000100")
        self.assertFalse(by_byte[0].has_movement)
        self.assertEqual(by_byte[0].series.label, "B0")
        self.assertTrue(by_byte[1].has_movement)
        self.assertEqual(by_byte[1].series.label, "B1")

    def test_has_movement_false_for_a_fully_constant_id(self):
        df = self._df("00000100", [1, 1, 1, 1])
        entries = build_matrix_summary(df, ["00000100"])
        self.assertEqual(len(entries), 2)
        self.assertFalse(entries[0].has_movement)
        self.assertFalse(entries[1].has_movement)

    def test_empty_dataframe_returns_no_entries(self):
        self.assertEqual(build_matrix_summary(pl.DataFrame(), ["00000100"]), [])

    def test_id_absent_from_the_dataframe_is_skipped(self):
        df = self._df("00000100", [1, 2, 1, 2])
        entries = build_matrix_summary(df, ["00000100", "00000200"])
        self.assertEqual({e.can_id for e in entries}, {"00000100"})

    def test_series_is_decimated_for_a_long_id(self):
        df = self._df("00000100", [i % 5 for i in range(2000)])
        entries = build_matrix_summary(df, ["00000100"], max_points=100)
        self.assertTrue(all(len(e.series.x) <= 100 for e in entries))

    def test_entries_for_every_id_independent_of_any_accumulator_cache(self):
        df = pl.concat([
            self._df("00000100", [i % 5 for i in range(10)]),
            self._df("00000200", [7] * 10),
        ], how="vertical_relaxed")
        entries = build_matrix_summary(df, ["00000100", "00000200"])
        self.assertEqual({e.can_id for e in entries}, {"00000100", "00000200"})
        self.assertEqual(len(entries), 4)  # 2 ids x 2 present bytes each

    def test_on_progress_and_cancel_hooks(self):
        df = self._df("00000100", [1, 2, 1, 2])
        seen = []
        build_matrix_summary(df, ["00000100"], on_progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen, [(1, 1)])

        with self.assertRaises(AnalyzeDataPrecomputeCanceled):
            build_matrix_summary(df, ["00000100"], should_cancel=lambda: True)


class BuildMatrixEntriesForIdTests(unittest.TestCase):
    """AN3 Live mode's cheap single-ID path -- must match build_matrix_summary()'s
    output for that same ID exactly, since the view can't tell which path built an
    entry."""

    def _df(self, can_id: str, b0_values: list[int], b1_values: list[int] | None = None) -> pl.DataFrame:
        n = len(b0_values)
        b1_values = b1_values if b1_values is not None else [9] * n
        return pl.DataFrame({
            "TS": [float(i) for i in range(n)],
            "ID": [can_id] * n,
            "LEN": [2] * n,
            "DATA": [f"{a:02X}{b:02X}" for a, b in zip(b0_values, b1_values)],
            "D0": b0_values,
            "D1": b1_values,
        })

    def test_matches_build_matrix_summary_for_the_same_id(self):
        df = pl.concat([
            self._df("00000100", [1, 1, 2, 2], [1, 2, 3, 4]),
            self._df("00000200", [7] * 4),
        ], how="vertical_relaxed")
        expected = build_matrix_summary(df, ["00000100"])
        actual = build_matrix_entries_for_id(df, "00000100")
        self.assertEqual(len(actual), len(expected))
        by_byte_expected = {e.byte_index: e for e in expected}
        by_byte_actual = {e.byte_index: e for e in actual}
        for idx, exp in by_byte_expected.items():
            act = by_byte_actual[idx]
            self.assertEqual(act.can_id, exp.can_id)
            self.assertEqual(act.has_movement, exp.has_movement)
            self.assertEqual(act.series, exp.series)

    def test_has_movement_false_for_a_fully_constant_id(self):
        df = self._df("00000100", [1, 1, 1, 1])
        entries = build_matrix_entries_for_id(df, "00000100")
        self.assertEqual(len(entries), 2)
        self.assertFalse(entries[0].has_movement)
        self.assertFalse(entries[1].has_movement)

    def test_id_absent_from_the_dataframe_returns_no_entries(self):
        df = self._df("00000100", [1, 2, 1, 2])
        self.assertEqual(build_matrix_entries_for_id(df, "00000200"), [])

    def test_empty_dataframe_returns_no_entries(self):
        self.assertEqual(build_matrix_entries_for_id(pl.DataFrame(), "00000100"), [])

    def test_series_is_decimated_for_a_long_id(self):
        df = self._df("00000100", [i % 5 for i in range(2000)])
        entries = build_matrix_entries_for_id(df, "00000100", max_points=100)
        self.assertTrue(all(len(e.series.x) <= 100 for e in entries))

    def test_single_row_has_no_movement(self):
        df = self._df("00000100", [1])
        entries = build_matrix_entries_for_id(df, "00000100")
        self.assertFalse(entries[0].has_movement)


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


def _patterned_df(n: int, *, seed: int) -> pl.DataFrame:
    """Synthetic ID frame: byte cols span constant / oscillating / counter / random
    patterns so vectorized change/entropy/timing paths all get exercised."""
    rng = random.Random(seed)
    ts = sorted(rng.uniform(0, 300) for _ in range(n))
    kinds = ["const", "toggle", "counter", "rand", "const", "toggle", "counter", "rand"]
    d_cols: dict[str, list] = {}
    for i, kind in enumerate(kinds):
        base = rng.randint(0, 255)
        tog = [rng.randint(0, 255), rng.randint(0, 255)]
        start = rng.randint(0, 255)
        vals = []
        for row in range(n):
            if kind == "const":
                vals.append(base)
            elif kind == "toggle":
                vals.append(tog[row % 2])
            elif kind == "counter":
                vals.append((start + row) % 256)
            else:
                vals.append(rng.randint(0, 4))
        d_cols[f"D{i}"] = vals
    data = ["".join(f"{d_cols[f'D{i}'][row]:02X}" for i in range(8)) for row in range(n)]
    return pl.DataFrame({
        "TS": ts, "ID": ["00000100"] * n, "LEN": [8] * n, "DATA": data, **d_cols,
    })


class VectorizedChunkingInvarianceTests(unittest.TestCase):
    """The vectorized feed() must stay chunk-boundary invariant: feeding a df whole
    equals feeding the same df split into arbitrary chunks, byte-for-byte on the
    snapshot dict -- including an out-of-order chunk that exercises the TS guards."""

    def _feed_chunked(self, df: pl.DataFrame, rng: random.Random) -> AnalyzeDataAccumulator:
        acc = AnalyzeDataAccumulator()
        i = 0
        while i < df.height:
            step = rng.randint(1, 40)
            acc.feed(df[i : i + step])
            i += step
        return acc

    def test_whole_equals_random_chunks(self):
        for seed, n in [(11, 50), (12, 97), (13, 200), (14, 333), (15, 500), (16, 128), (17, 271)]:
            df = _patterned_df(n, seed=seed)
            whole = AnalyzeDataAccumulator()
            whole.feed(df)
            chunked = self._feed_chunked(df, random.Random(seed * 3 + 1))
            self.assertEqual(
                chunked.snapshot("00000100", (0,), "All"),
                whole.snapshot("00000100", (0,), "All"),
                f"snapshot mismatch at seed={seed}, n={n}",
            )
            self.assertEqual(
                chunked.plot_series(set(range(8))),
                whole.plot_series(set(range(8))),
                f"plot mismatch at seed={seed}, n={n}",
            )

    def test_out_of_order_chunk_matches_whole_of_the_same_feed_order(self):
        # A late chunk whose TS are all below the already-fed watermark: order-guarded
        # stats (periods, byte update timing) must react identically whether the same
        # feed sequence is one accumulator or several.
        df_hi = _patterned_df(120, seed=21)
        df_lo = _patterned_df(60, seed=22).with_columns((pl.col("TS") - 10_000.0).alias("TS"))

        single = AnalyzeDataAccumulator()
        single.feed(df_hi)
        single.feed(df_lo)

        split = AnalyzeDataAccumulator()
        for start in range(0, df_hi.height, 13):
            split.feed(df_hi[start : start + 13])
        for start in range(0, df_lo.height, 7):
            split.feed(df_lo[start : start + 7])

        self.assertEqual(
            split.snapshot("00000100", (), "All"),
            single.snapshot("00000100", (), "All"),
        )


class OutOfOrderChunkTests(unittest.TestCase):
    """BUGS.md B-29: characterizes (doesn't change) feed()'s monotonic-TS guards
    when a chunk arrives with timestamps earlier than what's already been fed --
    e.g. multi-bus timestamp skew. Written before the vista matriz (AN1-AN4)
    multiplies this per-cell, so any future change here has a red/green anchor."""

    def _df(self, rows: list[tuple[float, int]]) -> pl.DataFrame:
        return pl.DataFrame({
            "TS": [ts for ts, _ in rows],
            "ID": ["00000100"] * len(rows),
            "LEN": [1] * len(rows),
            "DATA": [f"{b:02X}" for _, b in rows],
            "D0": [b for _, b in rows],
        })

    def test_frame_count_and_payload_stats_still_count_an_out_of_order_row(self):
        acc = AnalyzeDataAccumulator()
        acc.feed(self._df([(5.0, 1), (6.0, 2), (7.0, 3)]))
        acc.feed(self._df([(1.0, 9)]))  # arrives "late", ts before the last-seen 7.0

        snap = acc.snapshot("00000100", (), "All")
        self.assertEqual(snap["Frames"], 4)  # frame_count is unconditional
        self.assertEqual(snap["Distinct Payloads"], 4)  # payload set is unconditional

    def test_period_stats_silently_skip_the_out_of_order_row(self):
        acc = AnalyzeDataAccumulator()
        acc.feed(self._df([(5.0, 1), (6.0, 2), (7.0, 3)]))  # 2 periods of 1.0s each
        acc.feed(self._df([(1.0, 9)]))  # ts=1.0 < last_ts=7.0 -- guard skips it

        snap = acc.snapshot("00000100", (), "All")
        # Still only 2 periods (1.0, 1.0) -- no period computed against ts=1.0.
        self.assertEqual(snap["Mean Period"], "1.000000")
        self.assertEqual(snap["Min Period"], "1.000000")
        self.assertEqual(snap["Max Period"], "1.000000")

    def test_last_ts_does_not_regress(self):
        acc = AnalyzeDataAccumulator()
        acc.feed(self._df([(5.0, 1), (6.0, 2), (7.0, 3)]))
        acc.feed(self._df([(1.0, 9)]))
        self.assertEqual(acc._last_ts, 7.0)  # not regressed to 1.0

        # A subsequent well-ordered row after the out-of-order one still computes a
        # normal period against the true last_ts (7.0), not against the skipped 1.0.
        acc.feed(self._df([(9.0, 4)]))
        snap = acc.snapshot("00000100", (), "All")
        self.assertEqual(snap["Max Period"], "2.000000")

    def test_byte_change_count_is_unconditional_but_update_timing_stats_skip_it(self):
        acc = AnalyzeDataAccumulator()
        # val 1->2 (ts 5->6): first change, no delta yet (needs a prior change ts).
        # val 2->3 (ts 6->8): second change, delta=2.0s -- _byte_update_* gets a sample.
        acc.feed(self._df([(5.0, 1), (6.0, 2), (8.0, 3)]))
        acc.feed(self._df([(1.0, 9)]))  # val 3->9: differs -- change COUNTED...

        snap = acc.snapshot("00000100", (), "All")
        self.assertEqual(snap["Byte Changes"], "B0:3")  # ...all three changes counted
        # ...but the update-timing stats (seconds between changes) don't get a new
        # sample from it: ts=1.0 is before the last recorded change ts (8.0), so this
        # change's delta is skipped -- min/max/mean stay exactly what they were before.
        self.assertEqual(snap["Byte Update Min"], "B0:2.000000")
        self.assertEqual(snap["Byte Update Max"], "B0:2.000000")


class BuildAccumulatorTests(unittest.TestCase):
    def test_returns_accumulator_seeded_from_df(self):
        df = pl.DataFrame({"TS": [0.0, 1.0], "DATA": ["AA", "BB"], "D0": [1, 2]})
        acc = build_accumulator(df)
        self.assertIsInstance(acc, AnalyzeDataAccumulator)
        self.assertEqual(acc.snapshot(None, (), "All")["Frames"], 2)


class MuxBytesForCanIdTests(unittest.TestCase):
    def test_no_configs_returns_empty(self):
        self.assertEqual(mux_bytes_for_can_id([], "100"), ())

    def test_matches_by_can_id_case_insensitively(self):
        configs = [MuxConfigEntry(can_id="100", length=None, mux_bytes=(0,))]
        self.assertEqual(mux_bytes_for_can_id(configs, "100"), (0,))

    def test_prefers_the_length_none_entry_over_a_length_specific_one(self):
        configs = [
            MuxConfigEntry(can_id="100", length=8, mux_bytes=(1,)),
            MuxConfigEntry(can_id="100", length=None, mux_bytes=(0,)),
        ]
        self.assertEqual(mux_bytes_for_can_id(configs, "100"), (0,))

    def test_falls_back_to_any_matching_entry_when_no_length_none_exists(self):
        configs = [MuxConfigEntry(can_id="100", length=8, mux_bytes=(2,))]
        self.assertEqual(mux_bytes_for_can_id(configs, "100"), (2,))

    def test_unmatched_id_returns_empty(self):
        configs = [MuxConfigEntry(can_id="100", length=None, mux_bytes=(0,))]
        self.assertEqual(mux_bytes_for_can_id(configs, "200"), ())


def _multi_id_df(ids_and_counts: dict[str, int]) -> pl.DataFrame:
    rows = []
    for can_id, count in ids_and_counts.items():
        for ts in range(count):
            rows.append((float(ts), can_id, ts % 5))
    return pl.DataFrame({
        "TS": [r[0] for r in rows],
        "ID": [r[1] for r in rows],
        "LEN": [1] * len(rows),
        "DATA": [f"{r[2]:02X}" for r in rows],
        "D0": [r[2] for r in rows],
    })


class BuildAllAccumulatorsTests(unittest.TestCase):
    def test_builds_one_accumulator_per_id_matching_build_accumulator(self):
        df = _multi_id_df({"100": 5, "200": 3})
        result = build_all_accumulators(df, ["100", "200"], lambda _cid: ())

        self.assertEqual(set(result), {"100", "200"})
        acc_100, mux_cases_100 = result["100"]
        self.assertEqual(mux_cases_100, ["All"])
        expected_100 = build_accumulator(df.filter(pl.col("ID") == "100"))
        self.assertEqual(acc_100.snapshot("100", (), "All"), expected_100.snapshot("100", (), "All"))

    def test_reports_progress_per_id(self):
        df = _multi_id_df({"100": 2, "200": 2, "300": 2})
        seen = []
        build_all_accumulators(df, ["100", "200", "300"], lambda _cid: (), on_progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_cancels_via_should_cancel(self):
        df = _multi_id_df({"100": 2, "200": 2})
        calls = []

        def should_cancel():
            calls.append(1)
            return len(calls) > 1  # cancel right after the first id starts

        with self.assertRaises(AnalyzeDataPrecomputeCanceled):
            build_all_accumulators(df, ["100", "200"], lambda _cid: (), should_cancel=should_cancel)


if __name__ == "__main__":
    unittest.main()
