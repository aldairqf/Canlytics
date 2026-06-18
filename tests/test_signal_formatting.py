"""Characterization tests for services/signal_formatting."""

from __future__ import annotations

import unittest

from services.signal_formatting import format_signal_value, normalize_display_text


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


if __name__ == "__main__":
    unittest.main()
