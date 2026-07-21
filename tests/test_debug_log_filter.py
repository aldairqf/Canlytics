"""Characterization tests for services/debug_log_filter.py."""

from __future__ import annotations

import unittest

from services.debug_log_filter import DEFAULT_VISIBLE_LEVELS, extract_level, passes_filter

_DEBUG_LINE = "07-20 13:00:00.000 DEBUG/services.range_diff: computed diff"
_INFO_LINE = "07-20 13:00:00.000 INFO/viewmodels.data_viewmodel: log loaded"
_WARNING_LINE = "07-20 13:00:00.000 WARNING/services.dbc_manager: DBC restore skipped"
_ERROR_LINE = "07-20 13:00:00.000 ERROR/viewmodels.candidate_interpretations_viewmodel: search failed"
_ALL_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class ExtractLevelTests(unittest.TestCase):
    def test_extracts_each_level(self):
        self.assertEqual(extract_level(_DEBUG_LINE), "DEBUG")
        self.assertEqual(extract_level(_INFO_LINE), "INFO")
        self.assertEqual(extract_level(_WARNING_LINE), "WARNING")
        self.assertEqual(extract_level(_ERROR_LINE), "ERROR")

    def test_returns_none_for_an_unrecognized_line(self):
        self.assertIsNone(extract_level("not a log line at all"))


class PassesFilterTests(unittest.TestCase):
    def test_all_levels_checked_passes_everything(self):
        for line in (_DEBUG_LINE, _INFO_LINE, _WARNING_LINE, _ERROR_LINE):
            self.assertTrue(passes_filter(line, visible_levels=_ALL_LEVELS, tag_filter=""))

    def test_unchecked_level_is_hidden(self):
        self.assertFalse(passes_filter(_DEBUG_LINE, visible_levels={"INFO", "WARNING", "ERROR"}, tag_filter=""))
        self.assertTrue(passes_filter(_INFO_LINE, visible_levels={"INFO", "WARNING", "ERROR"}, tag_filter=""))
        self.assertTrue(passes_filter(_WARNING_LINE, visible_levels={"INFO", "WARNING", "ERROR"}, tag_filter=""))
        self.assertTrue(passes_filter(_ERROR_LINE, visible_levels={"INFO", "WARNING", "ERROR"}, tag_filter=""))

    def test_default_visible_levels_excludes_debug_only(self):
        self.assertEqual(DEFAULT_VISIBLE_LEVELS, {"INFO", "WARNING", "ERROR"})
        self.assertFalse(passes_filter(_DEBUG_LINE, visible_levels=DEFAULT_VISIBLE_LEVELS, tag_filter=""))
        for line in (_INFO_LINE, _WARNING_LINE, _ERROR_LINE):
            self.assertTrue(passes_filter(line, visible_levels=DEFAULT_VISIBLE_LEVELS, tag_filter=""))

    def test_no_levels_checked_hides_everything(self):
        for line in (_DEBUG_LINE, _INFO_LINE, _WARNING_LINE, _ERROR_LINE):
            self.assertFalse(passes_filter(line, visible_levels=set(), tag_filter=""))

    def test_tag_filter_matches_substring_of_the_logger_name(self):
        self.assertTrue(passes_filter(_DEBUG_LINE, visible_levels=_ALL_LEVELS, tag_filter="range_diff"))
        self.assertFalse(passes_filter(_DEBUG_LINE, visible_levels=_ALL_LEVELS, tag_filter="dbc_manager"))

    def test_tag_filter_and_level_combine(self):
        self.assertFalse(passes_filter(_DEBUG_LINE, visible_levels={"ERROR"}, tag_filter="range_diff"))
        self.assertTrue(passes_filter(_ERROR_LINE, visible_levels={"ERROR"}, tag_filter="candidate"))

    def test_unrecognized_line_is_always_hidden(self):
        self.assertFalse(passes_filter("not a log line", visible_levels=_ALL_LEVELS, tag_filter=""))


if __name__ == "__main__":
    unittest.main()
