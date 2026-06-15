"""Characterization tests for utils.timezone_format.format_timestamp.

These tests guard against the regression where large unix timestamps caused
pyqtgraph to append "(x1e+09)" to the axis label instead of human-readable
times, and ensure the formatting logic is correct across timezone modes.
"""

from __future__ import annotations

import math
import unittest

from utils.timezone_format import format_timestamp, format_timezone_label


# A real unix timestamp in the ~1.7e9 range — the scale that triggered the
# original "(x1e+09)" pyqtgraph bug.
_TS = 1_700_000_000  # 2023-11-14 22:13:20 UTC


class FormatTimestampModeNoneTests(unittest.TestCase):
    """When tz_mode is None or "none", return a decimal-seconds string."""

    def test_none_returns_decimal_seconds(self):
        result = format_timestamp(123.456, None)
        self.assertEqual(result, "123.46")

    def test_string_none_returns_decimal_seconds(self):
        result = format_timestamp(123.0, "none")
        self.assertEqual(result, "123.00")

    def test_large_timestamp_no_scientific_notation(self):
        # Regression: must not return anything resembling "1.70e+09" or "x1e+09".
        result = format_timestamp(_TS, "none")
        self.assertNotIn("e+", result.lower())
        self.assertNotIn("x1e", result.lower())
        self.assertTrue(result.startswith("1700000000"))

    def test_zero(self):
        self.assertEqual(format_timestamp(0.0, "none"), "0.00")

    def test_negative(self):
        self.assertEqual(format_timestamp(-5.5, "none"), "-5.50")


class FormatTimestampUTCTests(unittest.TestCase):
    """UTC mode returns HH:MM:SS in UTC."""

    def test_known_timestamp(self):
        # 1700000000 → 2023-11-14 22:13:20 UTC
        self.assertEqual(format_timestamp(_TS, "UTC"), "22:13:20")

    def test_midnight_utc(self):
        # 2023-11-14 00:00:00 UTC
        self.assertEqual(format_timestamp(1_699_920_000, "UTC"), "00:00:00")

    def test_format_is_hhmmss(self):
        result = format_timestamp(_TS, "UTC")
        parts = result.split(":")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p.isdigit() for p in parts))

    def test_no_scientific_notation(self):
        result = format_timestamp(_TS, "UTC")
        self.assertNotIn("e+", result.lower())
        self.assertNotIn("x1e", result.lower())


class FormatTimestampAmericaLimaTests(unittest.TestCase):
    """America/Lima (UTC-5) — the timezone shown in the bug screenshot."""

    def test_known_timestamp(self):
        # 1700000000 UTC → 2023-11-14 17:13:20 America/Lima (UTC-5)
        self.assertEqual(format_timestamp(_TS, "America/Lima"), "17:13:20")

    def test_format_is_hhmmss(self):
        result = format_timestamp(_TS, "America/Lima")
        parts = result.split(":")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p.isdigit() for p in parts))

    def test_no_scientific_notation(self):
        # Core regression guard: the result must never look like "(x1e+09)".
        result = format_timestamp(_TS, "America/Lima")
        self.assertNotIn("e+", result.lower())
        self.assertNotIn("x1e", result.lower())
        self.assertNotIn("1e9", result.lower())

    def test_different_from_utc(self):
        utc_result = format_timestamp(_TS, "UTC")
        lima_result = format_timestamp(_TS, "America/Lima")
        self.assertNotEqual(utc_result, lima_result)

    def test_offset_is_five_hours(self):
        utc_h = int(format_timestamp(_TS, "UTC").split(":")[0])
        lima_h = int(format_timestamp(_TS, "America/Lima").split(":")[0])
        # Lima is UTC-5, so lima_h == (utc_h - 5) % 24
        self.assertEqual(lima_h, (utc_h - 5) % 24)


class FormatTimestampEuropeTests(unittest.TestCase):
    def test_europe_berlin_cet(self):
        # 2023-11-14 22:13:20 UTC → 23:13:20 CET (UTC+1)
        result = format_timestamp(_TS, "Europe/Berlin")
        self.assertEqual(result, "23:13:20")

    def test_asia_tokyo(self):
        # 2023-11-14 22:13:20 UTC → 2023-11-15 07:13:20 JST (UTC+9)
        result = format_timestamp(_TS, "Asia/Tokyo")
        self.assertEqual(result, "07:13:20")


class FormatTimestampEdgeCasesTests(unittest.TestCase):
    def test_nan_returns_empty(self):
        self.assertEqual(format_timestamp(float("nan"), "UTC"), "")

    def test_inf_returns_empty(self):
        self.assertEqual(format_timestamp(math.inf, "UTC"), "")

    def test_neg_inf_returns_empty(self):
        self.assertEqual(format_timestamp(-math.inf, "America/Lima"), "")

    def test_unknown_timezone_falls_back_to_utc(self):
        # An unrecognised zone name must not raise — it silently uses UTC.
        result = format_timestamp(_TS, "Not/AZone")
        utc_result = format_timestamp(_TS, "UTC")
        self.assertEqual(result, utc_result)

    def test_none_mode_with_large_value_no_crash(self):
        result = format_timestamp(1.7e9, "none")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_list_of_timestamps_via_iteration(self):
        # Simulates what tickStrings does: format a batch of values.
        timestamps = [_TS + i * 3600 for i in range(5)]
        results = [format_timestamp(t, "America/Lima") for t in timestamps]
        for r in results:
            self.assertRegex(r, r"^\d{2}:\d{2}:\d{2}$")

    def test_zero_epoch_utc(self):
        # 1970-01-01 00:00:00 UTC
        self.assertEqual(format_timestamp(0.0, "UTC"), "00:00:00")


class FormatTimezoneLabelTests(unittest.TestCase):
    """Existing format_timezone_label function — guard against regression."""

    def test_utc(self):
        self.assertEqual(format_timezone_label("UTC"), "UTC (UTC+00:00)")

    def test_america_lima_offset(self):
        result = format_timezone_label("America/Lima")
        self.assertIn("UTC-05:00", result)
        self.assertIn("America/Lima", result)

    def test_unknown_zone_returns_as_is(self):
        self.assertEqual(format_timezone_label("Not/AZone"), "Not/AZone")


if __name__ == "__main__":
    unittest.main()
