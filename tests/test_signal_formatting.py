"""Characterization tests for services/signal_formatting."""

from __future__ import annotations

import unittest

from services.signal_formatting import (
    build_decode_display_lines,
    format_data_bytes,
    format_signal_value,
    normalize_display_text,
)


class FormatSignalValueTests(unittest.TestCase):
    def test_float_trims_trailing_zeros(self):
        self.assertEqual(format_signal_value(1.0), "1")
        self.assertEqual(format_signal_value(1.5), "1.5")
        self.assertEqual(format_signal_value(1.2300), "1.23")
        self.assertEqual(format_signal_value(0.0), "0")

    def test_non_float_uses_str(self):
        self.assertEqual(format_signal_value(5), "5")
        self.assertEqual(format_signal_value("abc"), "abc")


class NormalizeDisplayTextTests(unittest.TestCase):
    def test_none_passthrough(self):
        self.assertIsNone(normalize_display_text(None))

    def test_nbsp_and_strip(self):
        self.assertEqual(normalize_display_text("  a\xa0b  "), "a b")

    def test_repairs_latin1_utf8_mojibake(self):
        self.assertEqual(normalize_display_text("Â°C"), "°C")

    def test_plain_text_unchanged(self):
        self.assertEqual(normalize_display_text("rpm"), "rpm")


class FormatDataBytesTests(unittest.TestCase):
    """Was viewmodels/table_model.py's module-level format_data_bytes -- pure
    string formatting with no Qt dependency, moved here."""

    def test_bytes_are_space_separated(self):
        self.assertEqual(format_data_bytes("aabbcc"), "AA BB CC")

    def test_bits_mode_renders_8bit_binary_groups(self):
        self.assertEqual(format_data_bytes("ff01", as_bits=True), "11111111 00000001")

    def test_empty_and_none_return_empty_string(self):
        self.assertEqual(format_data_bytes(""), "")
        self.assertEqual(format_data_bytes(None), "")

    def test_odd_length_returned_unchanged(self):
        self.assertEqual(format_data_bytes("ABC"), "ABC")


class BuildDecodeDisplayLinesTests(unittest.TestCase):
    """Was viewmodels/table_model.py's inline loop inside _get_decode_cached --
    pure text formatting, moved here; the ViewModel keeps only the caching."""

    def test_one_line_per_item_with_unit_suffix(self):
        items = [{"name": "RPM", "value": 1000, "unit": "rpm"}, {"name": "Flag", "value": 1, "unit": ""}]
        text, line_map = build_decode_display_lines(items)
        self.assertEqual(text, "RPM: 1000 rpm\nFlag: 1")
        self.assertEqual(line_map, [0, 1])

    def test_empty_items_returns_empty_text_and_map(self):
        text, line_map = build_decode_display_lines([])
        self.assertEqual(text, "")
        self.assertEqual(line_map, [])


if __name__ == "__main__":
    unittest.main()
