"""Characterization tests for services/mux_detector.detect_fast_mux_patterns.

The detector is heuristic, so these tests pin the *contract* (return shape,
required columns, filtering) rather than exact detected patterns.
"""

from __future__ import annotations

import unittest

import polars as pl

from services.can_data_parser import frame_dict, rows_to_df
from services.mux_detector import FrameAnalysis, build_config_from_options, detect_fast_mux_patterns

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


class BuildConfigFromOptionsTests(unittest.TestCase):
    """Was viewmodels/mux_detection_viewmodel.py's private _build_config --
    moved here since it's detector-tuning business logic (a 0-100 strictness
    slider mapped to numeric thresholds), not UI adaptation."""

    def test_strictness_zero_is_most_permissive(self):
        cfg = build_config_from_options({"strictness": 0})
        self.assertEqual(cfg.discovery.min_support, 8)
        self.assertAlmostEqual(cfg.discovery.min_support_ratio, 0.01)
        self.assertEqual(cfg.discovery.max_patterns_per_group, 30)
        self.assertAlmostEqual(cfg.discovery.refinement_gain_threshold, 0.14)
        self.assertEqual(cfg.payload.max_decode_candidates, 14)

    def test_strictness_hundred_is_most_strict(self):
        cfg = build_config_from_options({"strictness": 100})
        self.assertEqual(cfg.discovery.min_support, 5)
        self.assertAlmostEqual(cfg.discovery.min_support_ratio, 0.03)
        self.assertEqual(cfg.discovery.max_patterns_per_group, 20)
        self.assertAlmostEqual(cfg.discovery.refinement_gain_threshold, 0.06)
        self.assertEqual(cfg.payload.max_decode_candidates, 10)

    def test_default_strictness_is_fifty(self):
        cfg = build_config_from_options({})
        self.assertEqual(cfg.discovery.min_support, 6)
        self.assertEqual(cfg.discovery.max_patterns_per_group, 25)

    def test_explicit_overrides_win_over_strictness_defaults(self):
        cfg = build_config_from_options({"strictness": 50, "min_support": 99})
        self.assertEqual(cfg.discovery.min_support, 99)

    def test_prefix_lengths_and_payload_flags_pass_through(self):
        cfg = build_config_from_options(
            {"prefix_lengths": [1, 5], "decode_bitfields": True, "decode_float32": False}
        )
        self.assertEqual(cfg.discovery.prefix_lengths, (1, 5))
        self.assertTrue(cfg.payload.enable_bitfields)
        self.assertFalse(cfg.payload.enable_float32)

    def test_empty_prefix_lengths_falls_back_to_default(self):
        cfg = build_config_from_options({"prefix_lengths": []})
        self.assertEqual(cfg.discovery.prefix_lengths, (1, 2, 3, 4))


if __name__ == "__main__":
    unittest.main()
