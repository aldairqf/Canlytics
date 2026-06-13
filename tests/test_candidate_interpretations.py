"""Characterization tests for services/candidate_interpretations pure logic."""

from __future__ import annotations

import unittest

from models.mux_config import MuxConfigEntry
from services.can_data_parser import frame_dict, rows_to_df
from services.candidate_interpretations import (
    _bit_positions,
    _build_candidate_items,
    _byte_order_options,
    _candidate_score,
    _format_number,
    _is_finite_number,
    _iter_signal_lengths,
    _mux_bytes_for_group,
    _overlaps_mux_bytes,
    _parse_mux_case_value,
    _passes_sensitivity,
    _value_type_options,
)


class ScoringTests(unittest.TestCase):
    def test_score_full_when_always_changing(self):
        self.assertAlmostEqual(_candidate_score([0.0, 1.0, 2.0], changes=2, distinct_values=3), 1.0)

    def test_score_zero_for_constant(self):
        self.assertEqual(_candidate_score([1.0, 1.0], changes=0, distinct_values=1), 0.0)

    def test_score_zero_for_single_value(self):
        self.assertEqual(_candidate_score([5.0], changes=0, distinct_values=1), 0.0)

    def test_sensitivity_threshold(self):
        # strictness 0 -> threshold 0.1 ; strictness 100 -> threshold 0.8
        self.assertTrue(_passes_sensitivity(0.5, 3, [0.0, 1.0, 2.0], sensitivity=0))
        self.assertFalse(_passes_sensitivity(0.5, 3, [0.0, 1.0, 2.0], sensitivity=100))

    def test_sensitivity_requires_two_distinct(self):
        self.assertFalse(_passes_sensitivity(1.0, 1, [1.0, 1.0], sensitivity=0))


class NumberHelpersTests(unittest.TestCase):
    def test_format_number(self):
        self.assertEqual(_format_number(3.0), "3")
        self.assertEqual(_format_number(-2.0), "-2")
        self.assertEqual(_format_number(1.5), "1.5")
        self.assertEqual(_format_number(1.25), "1.25")

    def test_is_finite_number(self):
        self.assertTrue(_is_finite_number("1.5"))
        self.assertFalse(_is_finite_number(float("nan")))
        self.assertFalse(_is_finite_number(float("inf")))
        self.assertFalse(_is_finite_number("abc"))
        self.assertFalse(_is_finite_number(None))


class OptionHelpersTests(unittest.TestCase):
    def test_byte_order_options(self):
        self.assertEqual(_byte_order_options("Little Endian"), [("LittleEndian", True)])
        self.assertEqual(_byte_order_options("Big Endian"), [("BigEndian", False)])
        self.assertEqual(_byte_order_options("Try Both"), [("LittleEndian", True), ("BigEndian", False)])

    def test_value_type_options(self):
        self.assertEqual(_value_type_options("Unsigned", 8), [("Unsigned", "uint")])
        self.assertEqual(_value_type_options("Float32", 8), [])
        self.assertEqual(_value_type_options("Float32", 32), [("Float32", "float32")])
        self.assertIn(("Float32", "float32"), _value_type_options("Try All", 32))
        self.assertNotIn(("Float32", "float32"), _value_type_options("Try All", 8))

    def test_iter_signal_lengths(self):
        self.assertEqual(list(_iter_signal_lengths(8, 8, 8)), [8])
        self.assertEqual(list(_iter_signal_lengths(1, 16, 8)), [1, 9, 16])


class MuxAndBitTests(unittest.TestCase):
    def test_mux_bytes_for_group_exact_then_fallback(self):
        configs = [MuxConfigEntry(can_id="100", length=8, mux_bytes=(0,))]
        self.assertEqual(_mux_bytes_for_group(configs, "100", 8), (0,))
        self.assertEqual(_mux_bytes_for_group(configs, "100", 6), ())
        any_len = [MuxConfigEntry(can_id="100", length=None, mux_bytes=(1,))]
        self.assertEqual(_mux_bytes_for_group(any_len, "100", 6), (1,))

    def test_parse_mux_case_value(self):
        self.assertEqual(_parse_mux_case_value("0A", (0,)), 0x0A)
        self.assertEqual(_parse_mux_case_value("0A 0B", (0, 1)), (0x0A << 8) | 0x0B)
        self.assertIsNone(_parse_mux_case_value("None", (0, 1)))
        self.assertIsNone(_parse_mux_case_value("ZZ", (0,)))
        self.assertIsNone(_parse_mux_case_value("00", ()))

    def test_bit_positions_little_endian(self):
        self.assertEqual(
            _bit_positions(start_bit=0, signal_length=8, is_little=True, available_bits=64),
            [0, 1, 2, 3, 4, 5, 6, 7],
        )
        self.assertIsNone(_bit_positions(start_bit=60, signal_length=8, is_little=True, available_bits=64))

    def test_bit_positions_big_endian_motorola(self):
        self.assertEqual(
            _bit_positions(start_bit=0, signal_length=8, is_little=False, available_bits=64),
            [0, 15, 14, 13, 12, 11, 10, 9],
        )

    def test_overlaps_mux_bytes(self):
        self.assertTrue(_overlaps_mux_bytes(start_bit=0, signal_length=8, mux_bytes=(0,), is_little=True, available_bits=64))
        self.assertFalse(_overlaps_mux_bytes(start_bit=0, signal_length=8, mux_bytes=(1,), is_little=True, available_bits=64))


class BuildCandidatesTests(unittest.TestCase):
    def test_ramp_yields_candidate(self):
        rows = [frame_dict(ts=i * 0.1, bus="b", can_id="100", data=bytes([i % 256, 0, 0, 0, 0, 0, 0, 0])) for i in range(20)]
        df = rows_to_df(rows)
        items = _build_candidate_items(
            df, checked_ids={"100"}, mux_configs=[],
            min_length=8, max_length=8, granularity=8,
            endianness="Little Endian", value_type="Unsigned", sensitivity=0,
        )
        self.assertTrue(items)
        self.assertEqual(items[0].can_id, "100")

    def test_empty_inputs(self):
        df = rows_to_df([])
        self.assertEqual(
            _build_candidate_items(df, checked_ids={"100"}, mux_configs=[], min_length=8, max_length=8,
                                   granularity=8, endianness="Little Endian", value_type="Unsigned", sensitivity=0),
            [],
        )


if __name__ == "__main__":
    unittest.main()
