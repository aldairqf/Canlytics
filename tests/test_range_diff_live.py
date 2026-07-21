"""Characterization tests for LiveByteAccumulator / build_live_diff_report.

Pins the core invariant Diff Analyzer's Live mode depends on: feeding a sequence
incrementally into LiveByteAccumulator must produce the exact same ByteObservation
as calling observe_byte() on the whole sequence at once. Also checks that
build_live_diff_report produces the same IdDiff shape as build_range_diff_report
for an equivalent baseline/live split.
"""

from __future__ import annotations

import unittest

from services.can_data_parser import frame_dict, rows_to_df
from services.range_diff import (
    LiveByteAccumulator,
    TimeRange,
    build_live_diff_report,
    build_range_diff_report,
    extract_byte_series,
    feed_live_accumulators,
    observe_byte,
    observe_dataframe_bytes,
)


def _row(ts, can_id, *byte_values, bus="b"):
    return frame_dict(ts=ts, bus=bus, can_id=can_id, data=bytes(byte_values))


def _fed(*values):
    acc = LiveByteAccumulator()
    for v in values:
        acc.feed(v)
    return acc


class LiveByteAccumulatorInvariantTests(unittest.TestCase):
    def test_constant_sequence(self):
        values = [5, 5, 5, 5]
        self.assertEqual(_fed(*values).snapshot(), observe_byte(values))

    def test_oscillating_sequence(self):
        values = [1, 2, 1, 3, 1, 2]
        self.assertEqual(_fed(*values).snapshot(), observe_byte(values))

    def test_counter_with_wrap(self):
        values = [253, 254, 255, 0, 1, 2]
        acc_obs = _fed(*values).snapshot()
        self.assertEqual(acc_obs, observe_byte(values))
        self.assertTrue(acc_obs.looks_counter)

    def test_toggle_between_two_values(self):
        values = [0, 1, 0, 1, 0, 1, 0]
        acc_obs = _fed(*values).snapshot()
        self.assertEqual(acc_obs, observe_byte(values))
        self.assertTrue(acc_obs.looks_counter)

    def test_single_value(self):
        values = [42]
        self.assertEqual(_fed(*values).snapshot(), observe_byte(values))

    def test_empty_accumulator_snapshot_does_not_raise(self):
        acc = LiveByteAccumulator()
        snap = acc.snapshot()
        self.assertEqual(snap.n_frames, 0)
        self.assertEqual(snap.values, ())
        self.assertFalse(snap.looks_counter)

    def test_incremental_feed_matches_batch_at_every_prefix(self):
        values = [10, 10, 12, 12, 12, 9, 8, 8, 8, 250, 251, 252]
        acc = LiveByteAccumulator()
        for i, v in enumerate(values):
            acc.feed(v)
            self.assertEqual(acc.snapshot(), observe_byte(values[: i + 1]))


class BuildLiveDiffReportEquivalenceTests(unittest.TestCase):
    def test_matches_batch_report_for_equivalent_split(self):
        rows = (
            [_row(ts, "100", 10, 20) for ts in (0.0, 1.0, 2.0)]
            + [_row(ts, "100", 99, 20) for ts in (10.0, 11.0, 12.0)]
        )
        df = rows_to_df(rows)

        batch = build_range_diff_report(df, TimeRange(0.0, 2.0), TimeRange(10.0, 12.0))

        baseline = {"100": [observe_byte([10, 10, 10]), observe_byte([20, 20, 20])] + [None] * 6}
        live_acc = {"100": [LiveByteAccumulator() for _ in range(8)]}
        for v in (99, 99, 99):
            live_acc["100"][0].feed(v)
        for v in (20, 20, 20):
            live_acc["100"][1].feed(v)

        live = build_live_diff_report(
            baseline, live_acc, range_a=TimeRange(0.0, 2.0), now=12.0
        )

        self.assertEqual(len(batch.ids), len(live.ids))
        batch_id, live_id = batch.ids[0], live.ids[0]
        self.assertEqual(batch_id.can_id, live_id.can_id)
        self.assertEqual(
            [(d.byte_index, d.change_type) for d in batch_id.byte_diffs],
            [(d.byte_index, d.change_type) for d in live_id.byte_diffs],
        )

    def test_only_baseline_id_reports_only_a(self):
        baseline = {"200": [observe_byte([1, 1, 1])] + [None] * 7}
        live_acc = {}
        report = build_live_diff_report(baseline, live_acc, range_a=TimeRange(0.0, 1.0), now=5.0)
        self.assertEqual(len(report.ids), 1)
        self.assertEqual(report.ids[0].presence, "only_a")

    def test_only_live_id_reports_only_b(self):
        acc = LiveByteAccumulator()
        for v in (1, 2, 3):
            acc.feed(v)
        live_acc = {"300": [acc] + [None] * 7}
        report = build_live_diff_report({}, live_acc, range_a=TimeRange(0.0, 1.0), now=5.0)
        self.assertEqual(len(report.ids), 1)
        self.assertEqual(report.ids[0].presence, "only_b")


class ObserveDataframeBytesTests(unittest.TestCase):
    def test_snapshots_every_id_and_byte(self):
        rows = [_row(0.0, "100", 10, 20), _row(1.0, "100", 12, 20), _row(0.0, "200", 5)]
        baseline = observe_dataframe_bytes(rows_to_df(rows))
        self.assertEqual(set(baseline), {"100", "200"})
        self.assertEqual(baseline["100"][0], observe_byte([10, 12]))
        self.assertEqual(baseline["100"][1], observe_byte([20, 20]))
        self.assertIsNone(baseline["100"][2])
        self.assertEqual(baseline["200"][0], observe_byte([5]))

    def test_empty_dataframe_returns_empty_dict(self):
        self.assertEqual(observe_dataframe_bytes(rows_to_df([])), {})


class FeedLiveAccumulatorsTests(unittest.TestCase):
    def test_feeds_new_ids_and_appends_to_existing(self):
        live_acc = {}
        feed_live_accumulators(live_acc, rows_to_df([_row(0.0, "100", 1), _row(1.0, "100", 2)]))
        self.assertEqual(live_acc["100"][0].snapshot(), observe_byte([1, 2]))

        feed_live_accumulators(live_acc, rows_to_df([_row(2.0, "100", 3), _row(0.0, "200", 9)]))
        self.assertEqual(live_acc["100"][0].snapshot(), observe_byte([1, 2, 3]))
        self.assertEqual(live_acc["200"][0].snapshot(), observe_byte([9]))

    def test_empty_new_df_is_a_no_op(self):
        live_acc = {"100": [LiveByteAccumulator() for _ in range(8)]}
        feed_live_accumulators(live_acc, rows_to_df([]))
        self.assertEqual(live_acc["100"][0].n_frames, 0)


class ExtractByteSeriesTests(unittest.TestCase):
    def test_returns_ts_and_values_for_the_given_id_and_byte(self):
        rows = [_row(0.0, "100", 1, 9), _row(1.0, "100", 2, 9), _row(0.0, "200", 5)]
        ts, values = extract_byte_series(rows_to_df(rows), "100", 0)
        self.assertEqual(ts, [0.0, 1.0])
        self.assertEqual(values, [1, 2])

    def test_unknown_id_returns_empty(self):
        ts, values = extract_byte_series(rows_to_df([_row(0.0, "100", 1)]), "999", 0)
        self.assertEqual((ts, values), ([], []))

    def test_empty_dataframe_returns_empty(self):
        ts, values = extract_byte_series(rows_to_df([]), "100", 0)
        self.assertEqual((ts, values), ([], []))


if __name__ == "__main__":
    unittest.main()
