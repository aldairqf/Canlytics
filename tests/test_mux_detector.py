"""Characterization tests for services/mux_detector.detect_fast_mux_patterns.

The detector is heuristic, so these tests pin the *contract* (return shape,
required columns, filtering) rather than exact detected patterns.
"""

from __future__ import annotations

import unittest

import numpy as np
import polars as pl

from services.can_data_parser import frame_dict, rows_to_df
from services.mux_detector import FrameAnalysis, _eta_squared, detect_fast_mux_patterns

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


def _recommended(analysis: FrameAnalysis):
    return [c for c in analysis.candidates if c.recommended]


def _state_payload(state: int, i: int) -> tuple[int, int, int, int]:
    """Bytes 2..5 all depend on ``state``, but on different ramps of ``i`` so
    no single one of them is a redundant copy of another -- only byte1 (the
    discriminator) is common to all of them."""
    byte2 = (state * 80 + (i % 20)) % 256
    byte3 = (state * 60 + (i % 15)) % 256
    byte4 = (state * 40 + (i % 10)) % 256
    byte5 = (state * 20 + (i % 5)) % 256
    return byte2, byte3, byte4, byte5


def _mid_frame_mux_df(n=60):
    """Real discriminator at byte1 (not the prefix), round-robin 0/1/2, with a
    constant, irrelevant byte0 -- the payload (bytes 2..5) depends on state."""
    rows = []
    for i in range(n):
        state = i % 3
        data = bytes([0xAA, state, *_state_payload(state, i)])
        rows.append(frame_dict(ts=i * 0.01, bus="b", can_id="300", data=data))
    return rows_to_df(rows)


def _decoy_plus_real_mux_df(n=60):
    """byte0 (parity of i) is an independent decoy; byte1 (i % 3) is the real
    discriminator gating bytes 2..5. gcd(2, 3) == 1, so conditioning on
    byte0's parity does not narrow down byte1's value at all."""
    rows = []
    for i in range(n):
        decoy = i % 2
        state = i % 3
        data = bytes([decoy, state, *_state_payload(state, i)])
        rows.append(frame_dict(ts=i * 0.01, bus="b", can_id="301", data=data))
    return rows_to_df(rows)


def _continuous_payload_mux_df(n=180):
    """byte0 is the discriminator; bytes 1-2 are continuously-varying signals
    whose *level* shifts per state without ever collapsing onto a handful of
    repeated values -- entropy alone under-scores this, eta-squared should
    not. Ramp periods (20, 25) are both coprime with the 3 states, so the
    ramp doesn't accidentally collapse into a low-cardinality proxy for the
    state itself."""
    rows = []
    for i in range(n):
        state = i % 3
        byte1 = (state * 80 + (i % 20)) % 256
        byte2 = (state * 60 + (i % 25)) % 256
        data = bytes([state, byte1, byte2, 0, 0])
        rows.append(frame_dict(ts=i * 0.01, bus="b", can_id="400", data=data))
    return rows_to_df(rows)


class MuxDetectorQualityTests(unittest.TestCase):
    """Pin detection *quality*, not just the return shape: a real mux
    discriminator anywhere in the frame must outrank an independent decoy,
    a round-robin discriminator must not be excluded just for cycling like a
    counter, and a continuous/analog payload must still be detectable."""

    def test_finds_discriminator_outside_the_prefix(self):
        analysis = detect_fast_mux_patterns(_mid_frame_mux_df(), "300")[6]
        recommended = _recommended(analysis)
        self.assertEqual(len(recommended), 1, "expected exactly one recommended candidate")
        self.assertEqual(recommended[0].byte_range, (1, 1))

    def test_round_robin_discriminator_is_not_excluded(self):
        analysis = detect_fast_mux_patterns(_mid_frame_mux_df(), "300")[6]
        winner = _recommended(analysis)[0]
        self.assertTrue(winner.counter_like, "byte1 cycles 0,1,2,0,1,2... -- should be flagged as cyclical")
        self.assertTrue(winner.recommended, "cycling like a counter must not block a real discriminator")

    def test_independent_decoy_is_not_recommended_over_real_mux(self):
        analysis = detect_fast_mux_patterns(_decoy_plus_real_mux_df(), "301")[6]
        recommended = _recommended(analysis)
        self.assertEqual(len(recommended), 1)
        self.assertEqual(recommended[0].byte_range, (1, 1), "the real discriminator (byte1) should win")
        decoy_candidates = [c for c in analysis.candidates if c.byte_range == (0, 0)]
        for candidate in decoy_candidates:
            self.assertFalse(candidate.recommended, "the independent decoy (byte0) must not be recommended")

    def test_at_most_one_recommended_candidate_per_group(self):
        for df, can_id, frame_len in (
            (_mid_frame_mux_df(), "300", 6),
            (_decoy_plus_real_mux_df(), "301", 6),
            (_continuous_payload_mux_df(), "400", 5),
        ):
            analysis = detect_fast_mux_patterns(df, can_id)[frame_len]
            self.assertLessEqual(len(_recommended(analysis)), 1, f"{can_id}: more than one recommended candidate")

    def test_continuous_analog_payload_is_still_detected(self):
        analysis = detect_fast_mux_patterns(_continuous_payload_mux_df(), "400")[5]
        recommended = _recommended(analysis)
        self.assertEqual(len(recommended), 1)
        self.assertEqual(recommended[0].byte_range, (0, 0))


class EtaSquaredTests(unittest.TestCase):
    def test_identical_groups_have_zero_dependency(self):
        groups = [np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 3.0])]
        self.assertAlmostEqual(_eta_squared(groups), 0.0, places=6)

    def test_perfectly_separated_groups_have_full_dependency(self):
        groups = [np.array([0.0, 0.0, 0.0]), np.array([10.0, 10.0, 10.0])]
        self.assertAlmostEqual(_eta_squared(groups), 1.0, places=6)

    def test_partial_separation_is_between_zero_and_one(self):
        groups = [np.array([0.0, 1.0, 2.0]), np.array([8.0, 9.0, 10.0])]
        score = _eta_squared(groups)
        self.assertGreater(score, 0.5)
        self.assertLess(score, 1.0)

    def test_single_group_has_zero_dependency(self):
        self.assertEqual(_eta_squared([np.array([1.0, 2.0, 3.0])]), 0.0)


if __name__ == "__main__":
    unittest.main()
