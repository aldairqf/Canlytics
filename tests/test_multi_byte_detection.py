"""Characterization tests for services/multi_byte_detection.py (P2.1).

Pins the carry-alignment heuristic empirically: a real 16-bit counter split into
low/high bytes must score high confidence; two independent random bytes must not
(false-positive check, not just a happy-path test) -- same "validate with real
numbers, not just plausibility" discipline as candidate_interpretations' scoring
(see CLAUDE.md).
"""

from __future__ import annotations

import random
import unittest

from services.multi_byte_detection import detect_carry_alignment, format_multi_byte_hint


def _split_16bit_counter(values: list[int]) -> tuple[list[int], list[int]]:
    low = [v % 256 for v in values]
    high = [(v // 256) % 256 for v in values]
    return low, high


class DetectCarryAlignmentTests(unittest.TestCase):
    def test_full_wraparound_16bit_counter_is_detected(self):
        values = list(range(0, 2000, 3))  # wraps low byte many times over the run
        low, high = _split_16bit_counter(values)
        hint = detect_carry_alignment(low, high, low_byte_index=0, high_byte_index=1)
        self.assertIsNotNone(hint)
        self.assertTrue(hint.is_multi_byte)
        self.assertGreaterEqual(hint.coincidence_ratio, 0.9)
        self.assertEqual(hint.low_byte_index, 0)
        self.assertEqual(hint.high_byte_index, 1)

    def test_decrementing_16bit_counter_is_also_detected(self):
        values = list(range(2000, 0, -5))
        low, high = _split_16bit_counter(values)
        hint = detect_carry_alignment(low, high, low_byte_index=2, high_byte_index=3)
        self.assertIsNotNone(hint)
        self.assertTrue(hint.is_multi_byte)

    def test_independent_random_bytes_are_not_flagged(self):
        # empirical false-positive check across many seeds, not a single lucky run
        false_positives = 0
        trials = 30
        for seed in range(trials):
            rng = random.Random(seed)
            low = [rng.randint(0, 255) for _ in range(500)]
            high = [rng.randint(0, 255) for _ in range(500)]
            hint = detect_carry_alignment(low, high, low_byte_index=0, high_byte_index=1)
            if hint is not None and hint.is_multi_byte:
                false_positives += 1
        self.assertEqual(false_positives, 0, f"{false_positives}/{trials} independent-byte trials falsely flagged")

    def test_constant_low_byte_reports_zero_wraps_not_none(self):
        # Zero evidence is still reported, distinct from "not enough data at all".
        low = [5] * 20
        high = [1, 2, 3] * 6 + [1, 2]
        hint = detect_carry_alignment(low, high, low_byte_index=0, high_byte_index=1)
        self.assertIsNotNone(hint)
        self.assertEqual(hint.wrap_count, 0)
        self.assertFalse(hint.is_multi_byte)

    def test_single_wrap_still_reports_real_numbers(self):
        # A lone wrap event reports its actual (weak but real) evidence, not a null.
        low = [250, 251, 252, 253, 254, 0, 1, 2]  # exactly one wrap event
        high = [0, 0, 0, 0, 0, 1, 1, 1]  # carried correctly, but only once
        hint = detect_carry_alignment(low, high, low_byte_index=0, high_byte_index=1)
        self.assertIsNotNone(hint)
        self.assertEqual(hint.wrap_count, 1)
        self.assertEqual(hint.coincidence_ratio, 1.0)

    def test_mismatched_lengths_returns_none(self):
        self.assertIsNone(detect_carry_alignment([1, 2, 3], [1, 2], low_byte_index=0, high_byte_index=1))

    def test_too_short_returns_none(self):
        self.assertIsNone(detect_carry_alignment([1], [1], low_byte_index=0, high_byte_index=1))

    def test_wraps_with_no_carry_are_not_flagged(self):
        # low byte wraps repeatedly but high byte never moves -- not multi-byte.
        low = ([0, 64, 128, 192, 255, 0] * 10)
        high = [7] * len(low)
        hint = detect_carry_alignment(low, high, low_byte_index=0, high_byte_index=1)
        self.assertIsNotNone(hint)
        self.assertFalse(hint.is_multi_byte)
        self.assertEqual(hint.coincidence_ratio, 0.0)


class FormatMultiByteHintTests(unittest.TestCase):
    def test_none_hint_formats_empty(self):
        self.assertEqual(format_multi_byte_hint(None), "")

    def test_non_multi_byte_hint_still_reports_real_numbers(self):
        values = list(range(0, 2000, 3))
        low, high = _split_16bit_counter(values)
        weak_hint = detect_carry_alignment(low, [0] * len(high), low_byte_index=0, high_byte_index=1)
        text = format_multi_byte_hint(weak_hint)
        self.assertIn("0% carry", text)
        self.assertNotIn("likely 16-bit", text)

    def test_zero_wrap_hint_formats_as_no_wraps_observed(self):
        hint = detect_carry_alignment([5] * 20, list(range(20)), low_byte_index=0, high_byte_index=1)
        self.assertEqual(format_multi_byte_hint(hint), "B1: no wrap events observed")

    def test_multi_byte_hint_mentions_the_paired_byte(self):
        values = list(range(0, 2000, 3))
        low, high = _split_16bit_counter(values)
        hint = detect_carry_alignment(low, high, low_byte_index=2, high_byte_index=3)
        text = format_multi_byte_hint(hint)
        self.assertIn("B3", text)


if __name__ == "__main__":
    unittest.main()
