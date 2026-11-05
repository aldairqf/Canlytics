from __future__ import annotations

import unittest

from services.can_data_parser import frame_dict, rows_to_df
from services.offline_realtime import OfflineRealtimeIndex


def _row(ts: float, can_id: str, value: int) -> dict:
    return frame_dict(ts=ts, bus="b", can_id=can_id, data=bytes([value]))


class OfflineRealtimeIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = OfflineRealtimeIndex(rows_to_df([
            _row(3.0, "100", 3),
            _row(1.0, "100", 1),
            _row(2.0, "200", 2),
            _row(2.0, "100", 22),
        ]))

    def test_snapshot_uses_latest_frame_at_or_before_cursor_per_id(self):
        snapshot = self.index.snapshot_at(2.0).sort("ID")
        self.assertEqual(snapshot.select("ID", "TS", "D0").rows(), [
            ("100", 2.0, 22), ("200", 2.0, 2),
        ])

    def test_snapshot_before_first_frame_is_empty(self):
        self.assertTrue(self.index.snapshot_at(0.5).is_empty())

    def test_snapshot_delta_is_interval_to_previous_frame_of_same_id(self):
        snapshot = self.index.snapshot_at(3.0)
        row = snapshot.filter(snapshot["ID"] == "100").row(0, named=True)
        self.assertEqual(row["Delta T"], 1.0)

    def test_duplicate_timestamp_chooses_last_frame_in_source_order(self):
        row = self.index.snapshot_at(2.0).filter(self.index.snapshot_at(2.0)["ID"] == "100").row(0, named=True)
        self.assertEqual(row["D0"], 22)

    def test_global_time_positions_collapse_duplicate_timestamps(self):
        self.assertEqual(self.index.frame_count, 4)
        self.assertEqual(self.index.position_count, 3)
        self.assertEqual(self.index.index_at(2.0), 1)
        self.assertEqual(self.index.index_at(0.5), -1)
        self.assertEqual(self.index.timestamp_at(-1), 1.0)
        self.assertEqual(self.index.timestamp_at(1), 2.0)
        self.assertEqual(self.index.timestamp_at(100), 3.0)


if __name__ == "__main__":
    unittest.main()
