"""Characterization tests for the shared helpers extracted in Fase 1."""

from __future__ import annotations

import unittest

from utils.can_bytes import parse_hex_bytes
from utils.can_id import can_id_sort_key, can_id_to_int
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


if __name__ == "__main__":
    unittest.main()
