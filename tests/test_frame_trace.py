from __future__ import annotations

import unittest

import polars as pl

from models.trace_filter import TraceFilter
from services.frame_trace import ChangedBytesTracker, filter_trace_rows


def _frames(ids: list[str], payloads: list[str]) -> pl.DataFrame:
    return pl.DataFrame({"ID": ids, "LEN": [len(payload) // 2 for payload in payloads], "DATA": payloads})


class ChangedBytesTrackerTests(unittest.TestCase):
    def test_compares_only_with_previous_frame_of_same_id(self):
        tracker = ChangedBytesTracker()
        annotated = tracker.annotate(
            _frames(["100", "200", "100", "200", "100"], ["010203", "AABB", "010203", "AABC", "FF020304"])
        )
        self.assertEqual(annotated["_ChangedBytes"].to_list(), ["", "", "", "1", "0,3"])

    def test_preserves_state_between_chunks_and_tracks_dlc_changes(self):
        tracker = ChangedBytesTracker()
        first = tracker.annotate(_frames(["100"], ["0102"]))
        second = tracker.annotate(_frames(["100", "100"], ["010203", "01"]))
        self.assertEqual(first["_ChangedBytes"].to_list(), [""])
        self.assertEqual(second["_ChangedBytes"].to_list(), ["2", "1,2"])

    def test_reset_makes_first_frame_of_each_source_a_baseline(self):
        tracker = ChangedBytesTracker()
        tracker.annotate(_frames(["100"], ["01"]))
        tracker.reset()
        result = tracker.annotate(_frames(["100"], ["FF"]))
        self.assertEqual(result["_ChangedBytes"].to_list(), [""])


class TraceFilterTests(unittest.TestCase):
    def setUp(self):
        self.df = pl.DataFrame(
            {
                "ID": ["100", "100", "200", "200"],
                "LEN": [2, 2, 1, 2],
                "DATA": ["00AB", "00A1", "FF", "10AB"],
                "_ChangedBytes": ["", "1", "", "0,1"],
            }
        )

    def test_filters_byte_value_with_mask_and_dlc(self):
        filtered = filter_trace_rows(
            self.df,
            TraceFilter(byte_index=1, mask=0xF0, value=0xA0, dlc=2),
        )
        self.assertEqual(filtered["DATA"].to_list(), ["00AB", "00A1", "10AB"])

    def test_only_changes_excludes_first_frame_per_id(self):
        filtered = filter_trace_rows(self.df, TraceFilter(only_changes=True))
        self.assertEqual(filtered["DATA"].to_list(), ["00A1", "10AB"])

    def test_mask_without_value_matches_set_bits(self):
        filtered = filter_trace_rows(self.df, TraceFilter(byte_index=0, mask=0x10))
        self.assertEqual(filtered["DATA"].to_list(), ["FF", "10AB"])


if __name__ == "__main__":
    unittest.main()
