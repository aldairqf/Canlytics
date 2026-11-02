from __future__ import annotations

import unittest

import polars as pl

from services.bus_statistics import BusStatisticsAccumulator


def frames(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema={"TS": pl.Float64, "Bus": pl.Utf8, "ID": pl.Utf8, "LEN": pl.UInt8})


class BusStatisticsTests(unittest.TestCase):
    def test_computes_bus_and_per_id_rates_and_periods_incrementally(self):
        tracker = BusStatisticsAccumulator()
        tracker.ingest(frames([
            {"TS": 0.0, "Bus": "can0", "ID": "123", "LEN": 2},
            {"TS": 0.1, "Bus": "can0", "ID": "123", "LEN": 2},
        ]), arrival_time=10)
        tracker.ingest(frames([
            {"TS": 0.3, "Bus": "can0", "ID": "123", "LEN": 2},
            {"TS": 0.4, "Bus": "can0", "ID": "456", "LEN": 1},
        ]), arrival_time=11)

        result = tracker.snapshot(bitrate=125_000, now=11)
        first = result.can_ids[0]
        self.assertEqual(result.frame_count, 4)
        self.assertEqual(result.can_id_count, 2)
        self.assertAlmostEqual(result.frames_per_second, 7.5)
        self.assertEqual(first.can_id, "123")
        self.assertAlmostEqual(first.frames_per_second, 2 / 0.3)
        self.assertAlmostEqual(first.period_min, 0.1)
        self.assertAlmostEqual(first.period_mean, 0.15)
        self.assertAlmostEqual(first.period_max, 0.2)
        self.assertAlmostEqual(first.jitter, 0.05)
        self.assertAlmostEqual(result.estimated_load_percent, 0.59, places=1)
        self.assertEqual(result.new_ids, ("123", "456"))

    def test_seed_establishes_baseline_and_empty_chunks_are_ignored(self):
        tracker = BusStatisticsAccumulator()
        tracker.seed(frames([{"TS": 1.0, "Bus": "can0", "ID": "001", "LEN": 0}]))
        tracker.ingest(frames([]))
        tracker.ingest(frames([{"TS": 2.0, "Bus": "can0", "ID": "002", "LEN": 1}]))

        result = tracker.snapshot(now=5, live=False)
        self.assertEqual(result.frame_count, 2)
        self.assertEqual(result.new_ids, ("002",))
        self.assertEqual(result.missing_ids, ())

    def test_live_ids_become_missing_then_return_to_active(self):
        tracker = BusStatisticsAccumulator(missing_after_seconds=2)
        data = frames([{"TS": 1.0, "Bus": "can0", "ID": "001", "LEN": 0}])
        tracker.ingest(data, arrival_time=10)
        self.assertEqual(tracker.snapshot(live=True, now=12).missing_ids, ("001",))
        tracker.ingest(frames([{"TS": 2.0, "Bus": "can0", "ID": "001", "LEN": 0}]), arrival_time=12)
        self.assertEqual(tracker.snapshot(live=True, now=12).missing_ids, ())

    def test_load_is_unavailable_without_bitrate_or_for_multiple_buses(self):
        tracker = BusStatisticsAccumulator()
        tracker.ingest(frames([
            {"TS": 0.0, "Bus": "can0", "ID": "123", "LEN": 1},
            {"TS": 1.0, "Bus": "can1", "ID": "123", "LEN": 1},
        ]))
        self.assertIsNone(tracker.snapshot(bitrate=500_000).estimated_load_percent)
        self.assertIsNone(tracker.snapshot().estimated_load_percent)

    def test_zero_epoch_timestamp_keeps_nonzero_duration(self):
        tracker = BusStatisticsAccumulator()
        tracker.ingest(frames([
            {"TS": 0.0, "Bus": "can0", "ID": "123", "LEN": 1},
            {"TS": 1.0, "Bus": "can0", "ID": "123", "LEN": 1},
        ]))
        result = tracker.snapshot(bitrate=500_000)
        self.assertEqual(result.frames_per_second, 1)
        self.assertIsNotNone(result.estimated_load_percent)

    def test_late_chunk_marks_period_statistics_unreliable(self):
        tracker = BusStatisticsAccumulator()
        tracker.ingest(frames([
            {"TS": 1.0, "Bus": "can0", "ID": "123", "LEN": 1},
            {"TS": 3.0, "Bus": "can0", "ID": "123", "LEN": 1},
        ]))
        tracker.ingest(frames([{"TS": 2.0, "Bus": "can0", "ID": "123", "LEN": 1}]))
        tracker.ingest(frames([{"TS": 4.0, "Bus": "can0", "ID": "123", "LEN": 1}]))

        result = tracker.snapshot().can_ids[0]
        self.assertEqual(result.frame_count, 4)
        self.assertFalse(result.periods_reliable)
        self.assertIsNone(result.period_min)
        self.assertIsNone(result.period_mean)
        self.assertIsNone(result.period_max)
        self.assertIsNone(result.jitter)
        self.assertEqual(result.frames_per_second, 1.0)

    def test_three_periodic_frames_use_two_elapsed_intervals(self):
        tracker = BusStatisticsAccumulator()
        tracker.ingest(frames([
            {"TS": 0.0, "Bus": "can0", "ID": "123", "LEN": 1},
            {"TS": 0.1, "Bus": "can0", "ID": "123", "LEN": 1},
            {"TS": 0.2, "Bus": "can0", "ID": "123", "LEN": 1},
        ]))

        result = tracker.snapshot()
        self.assertAlmostEqual(result.frames_per_second, 10.0)
        self.assertAlmostEqual(result.can_ids[0].frames_per_second, 10.0)


if __name__ == "__main__":
    unittest.main()
