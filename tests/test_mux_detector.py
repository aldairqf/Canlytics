"""Characterization tests for services/mux_detector.detect_fast_mux_patterns.

The detector is heuristic, so these tests pin the *contract* (return shape,
required columns, filtering) rather than exact detected patterns.
"""

from __future__ import annotations

import unittest

import polars as pl

from services.can_data_parser import frame_dict, rows_to_df
from services.mux_detector import FrameAnalysis, detect_fast_mux_patterns

FRAME_COUNT = 30


def _muxed_df():
    rows = []
    for i in range(FRAME_COUNT):
        mux = i % 3
        data = bytes([mux, i % 256, (i * 7) % 256, 0, 0, 0, 0, 0])
        rows.append(frame_dict(ts=i * 0.01, bus="b", can_id="100", data=data))
    return rows_to_df(rows)


class DetectFastMuxPatternsTests(unittest.TestCase):
    def test_returns_analysis_keyed_by_frame_len(self):
        result = detect_fast_mux_patterns(_muxed_df(), "100")
        self.assertIsInstance(result, dict)
        self.assertIn(8, result)
        analysis = result[8]
        self.assertIsInstance(analysis, FrameAnalysis)
        self.assertEqual(analysis.frame_len, 8)
        self.assertEqual(analysis.total_frames, FRAME_COUNT)
        self.assertEqual(analysis.can_id, "100")

    def test_unknown_id_returns_empty(self):
        self.assertEqual(detect_fast_mux_patterns(_muxed_df(), "999"), {})

    def test_missing_required_column_raises(self):
        df = pl.DataFrame({"ID": ["100"], "TS": [0.0]})  # no LEN
        with self.assertRaises(ValueError):
            detect_fast_mux_patterns(df, "100")


if __name__ == "__main__":
    unittest.main()
