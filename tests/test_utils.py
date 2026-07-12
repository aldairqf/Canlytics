"""Characterization tests for the shared helpers extracted in Fase 1."""

from __future__ import annotations

import unittest

from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_sort_key, can_id_to_int, can_id_to_int_or_none
from utils.dbc_payload import DbcPayload
from utils.j1939 import J1939
from utils.timezone_format import format_timezone_label


class ParseHexBytesTests(unittest.TestCase):
    def test_even_length(self):
        self.assertEqual(parse_hex_bytes("0102FF"), b"\x01\x02\xff")

    def test_odd_length_is_right_padded_with_zero_nibble(self):
        # "1" -> "10" -> 0x10
        self.assertEqual(parse_hex_bytes("1"), b"\x10")

    def test_empty_and_none(self):
        self.assertEqual(parse_hex_bytes(""), b"")
        self.assertEqual(parse_hex_bytes(None), b"")

    def test_invalid_hex_returns_empty(self):
        self.assertEqual(parse_hex_bytes("ZZ"), b"")


class CanIdToIntTests(unittest.TestCase):
    def test_parses_hex(self):
        self.assertEqual(can_id_to_int("18FEF100"), 0x18FEF100)
        self.assertEqual(can_id_to_int("100"), 256)

    def test_non_string_is_stringified_then_parsed_as_hex(self):
        # int input is stringified first: int(str(256), 16) -> int("256", 16) == 598.
        # Real callers always pass hex strings; this documents the quirk.
        self.assertEqual(can_id_to_int(256), 598)

    def test_invalid_raises_value_error(self):
        with self.assertRaises(ValueError):
            can_id_to_int("ZZ")


class CanIdToIntOrNoneTests(unittest.TestCase):
    """Tolerant counterpart to can_id_to_int -- used by services/can_decoder.py
    and services/signal_coverage.py, which each used to reimplement this same
    try/except wrapper privately instead of sharing one utils/ helper."""

    def test_parses_hex(self):
        self.assertEqual(can_id_to_int_or_none("18FEF100"), 0x18FEF100)
        self.assertEqual(can_id_to_int_or_none("100"), 256)

    def test_empty_and_none_return_none(self):
        self.assertIsNone(can_id_to_int_or_none(None))
        self.assertIsNone(can_id_to_int_or_none(""))

    def test_invalid_returns_none_instead_of_raising(self):
        self.assertIsNone(can_id_to_int_or_none("ZZ"))


class CanIdSortKeyTests(unittest.TestCase):
    def test_hex_ids_sort_numerically(self):
        self.assertEqual(can_id_sort_key("100"), (0, 256))
        self.assertEqual(can_id_sort_key(" 1ab "), (0, 0x1AB))

    def test_non_hex_pushed_to_end(self):
        self.assertEqual(can_id_sort_key("GG"), (1, "GG"))

    def test_sorting_order(self):
        ids = ["200", "100", "ZZZ", "0A"]
        self.assertEqual(sorted(ids, key=can_id_sort_key), ["0A", "100", "200", "ZZZ"])


class FormatTimezoneLabelTests(unittest.TestCase):
    def test_utc(self):
        self.assertEqual(format_timezone_label("UTC"), "UTC (UTC+00:00)")

    def test_unknown_zone_returns_raw_name(self):
        self.assertEqual(format_timezone_label("Not/AZone"), "Not/AZone")

    def test_known_zone_has_offset_suffix(self):
        # Offset value depends on DST rules; only pin the format shape.
        label = format_timezone_label("America/Lima")
        self.assertTrue(label.startswith("America/Lima (UTC"))
        self.assertTrue(label.endswith(")"))


class ExtractPgnTests(unittest.TestCase):
    """Pins J1939.extract_pgn, the single source of truth every decoder delegates to."""

    def test_pdu2_broadcast_includes_group_extension(self):
        self.assertEqual(J1939.extract_pgn(can_id_to_int("18FEE300")), 0xFEE3)

    def test_pdu1_ignores_destination_address(self):
        self.assertEqual(J1939.extract_pgn(can_id_to_int("18EF0A0B")), 0xEF00)
        self.assertEqual(J1939.extract_pgn(can_id_to_int("18EF140C")), 0xEF00)

    def test_real_pgn_zero_frame(self):
        self.assertEqual(J1939.extract_pgn(can_id_to_int("0C000000")), 0)

    def test_standard_range_ids_have_no_pgn(self):
        for raw_id in ("006", "007", "107", "7FF"):
            self.assertIsNone(J1939.extract_pgn(can_id_to_int(raw_id)))


class FormatPgnTests(unittest.TestCase):
    def test_formats_as_four_digit_hex(self):
        self.assertEqual(J1939.format_pgn(0x200), "0x0200")
        self.assertEqual(J1939.format_pgn(0xFECA), "0xFECA")

    def test_none_stays_none(self):
        self.assertIsNone(J1939.format_pgn(None))


class PgnToFrameIdTests(unittest.TestCase):
    """Pins J1939.pgn_to_frame_id, the inverse used to synthesize ids for generated DBCs."""

    def test_round_trips_through_extract_pgn_for_pdu2(self):
        frame_id = J1939.pgn_to_frame_id(0xFEE3, priority=6, source_address=0x11)
        self.assertEqual(J1939.extract_pgn(frame_id), 0xFEE3)

    def test_round_trips_through_extract_pgn_for_pdu1(self):
        frame_id = J1939.pgn_to_frame_id(0xEF00, priority=3, source_address=0x0B)
        self.assertEqual(J1939.extract_pgn(frame_id), 0xEF00)

    def test_priority_and_source_address_occupy_expected_bits(self):
        frame_id = J1939.pgn_to_frame_id(0xF003, priority=3, source_address=0x11)
        self.assertEqual(frame_id, 0x0CF00311)

    def test_defaults_are_priority_six_and_source_zero(self):
        frame_id = J1939.pgn_to_frame_id(0xF003)
        self.assertEqual(frame_id, 0x18F00300)


class DbcPayloadExtractBitsTests(unittest.TestCase):
    def test_little_endian(self):
        # D0=0x34, D1=0x12 -> LE bits 0..15 -> 0x1234
        self.assertEqual(DbcPayload.extract_bits(bytes([0x34, 0x12]), 0, 16, True), 0x1234)

    def test_big_endian(self):
        # D0=0xFF; BE len8 start0 reads bit0 into MSB position -> 128
        self.assertEqual(DbcPayload.extract_bits(bytes([0xFF]), 0, 8, False), 128)


class DbcPayloadMuxValueTests(unittest.TestCase):
    def test_single_byte(self):
        self.assertEqual(DbcPayload.mux_value(bytes([0x02, 0xAA]), 0, 1), 2)

    def test_multi_byte_is_big_endian(self):
        self.assertEqual(DbcPayload.mux_value(bytes([0x01, 0x02, 0x03]), 0, 2), 0x0102)

    def test_missing_trailing_bytes_count_as_zero(self):
        # Only byte 0 (0x01) present; bytes 1-2 missing -> keeps its high-order weight.
        self.assertEqual(DbcPayload.mux_value(bytes([0x01]), 0, 3), 0x010000)


if __name__ == "__main__":
    unittest.main()
