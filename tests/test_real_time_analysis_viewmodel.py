"""Characterization tests for RealTimeAnalysisViewModel's CAN-id index upkeep."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtWidgets import QApplication

from config.app_config import get_text
from models.mux_config import MuxConfigEntry
from services.can_data_parser import frame_dict, rows_to_df
from viewmodels.real_time_analysis_viewmodel import RealTimeAnalysisViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


def _row(ts: float, can_id: str, byte0: int) -> dict:
    return frame_dict(ts=ts, bus="b", can_id=can_id, data=bytes([byte0]))


class IdToEntriesIndexTests(unittest.TestCase):
    def setUp(self):
        self.vm = RealTimeAnalysisViewModel()

    def test_details_for_selection_uses_the_index(self):
        self.vm.ingest_df(rows_to_df([_row(1.0, "100", 1), _row(1.0, "101", 2)]))
        data = self.vm.details_data_for_selection({"100"})
        self.assertEqual(data["id"], "100")
        self.assertNotIn("empty", data)

    def test_repeated_frames_for_same_id_update_the_indexed_entry_in_place(self):
        self.vm.ingest_df(rows_to_df([_row(1.0, "100", 1)]))
        self.vm.ingest_df(rows_to_df([_row(2.0, "100", 2)]))
        entries = self.vm._id_to_entries["100"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].frame_count, 2)

    def test_unknown_id_returns_empty_state_not_a_scan(self):
        self.vm.ingest_df(rows_to_df([_row(1.0, "100", 1)]))
        data = self.vm.details_data_for_selection({"1FF"})
        self.assertIn("empty", data)

    def test_clear_resets_the_index(self):
        self.vm.ingest_df(rows_to_df([_row(1.0, "100", 1)]))
        self.vm.clear()
        data = self.vm.details_data_for_selection({"100"})
        self.assertIn("empty", data)


class HighlightExpiryTimerIndependenceTests(unittest.TestCase):
    """BUGS.md B-07: highlight_hold must not be bound to refresh_interval -- there must
    be two independent timers, and changing one must never change the other's cadence."""

    def setUp(self):
        self.vm = RealTimeAnalysisViewModel()

    def test_two_separate_timers_exist(self):
        self.assertIsNot(self.vm._refresh_timer, self.vm._highlight_expiry_timer)

    def test_changing_refresh_interval_does_not_change_highlight_expiry_cadence(self):
        original_expiry_interval = self.vm._highlight_expiry_timer.interval()
        self.vm.set_refresh_interval_ms(5000)
        self.assertEqual(self.vm._highlight_expiry_timer.interval(), original_expiry_interval)

    def test_changing_highlight_hold_does_not_change_refresh_cadence(self):
        original_refresh_interval = self.vm._refresh_timer.interval()
        self.vm.set_highlight_hold_ms(10000)
        self.assertEqual(self.vm._refresh_timer.interval(), original_refresh_interval)


class DetailsLookupIndependenceTests(unittest.TestCase):
    """Supports BUGS.md B-06 (the window-level "stuck details panel" bug, verified with
    a manual smoke test -- see TESTS.md's note on not building QMainWindows in this
    suite): the vm's own by-row and by-selection lookups don't interfere with each
    other, so a window-level "clear selection" affordance can freely switch between
    them without the vm carrying hidden state across the switch."""

    def setUp(self):
        self.vm = RealTimeAnalysisViewModel()

    def test_details_for_selection_works_after_a_row_lookup_and_back(self):
        self.vm.ingest_df(rows_to_df([_row(1.0, "100", 1), _row(1.0, "200", 2)]))
        row_data = self.vm.details_data_for_row({"ID": "100"})
        self.assertEqual(row_data["id"], "100")
        selection_data = self.vm.details_data_for_selection({"200"})
        self.assertEqual(selection_data["id"], "200")


class LocalizedSummaryTextTests(unittest.TestCase):
    """B-12: these summaries must come from get_text()/ui_text.py, not a hardcoded
    English literal that would silently override the app's localized text."""

    def setUp(self):
        self.vm = RealTimeAnalysisViewModel()

    def test_mux_summary_none(self):
        self.assertEqual(self.vm.mux_configuration_summary(), get_text("realtime_mux_summary_none"))

    def test_mux_summary_with_rules(self):
        self.vm.set_mux_configuration([MuxConfigEntry(can_id="100", length=None, mux_bytes=(0,))])
        expected = get_text("realtime_mux_summary_rules").format(count=1)
        self.assertEqual(self.vm.mux_configuration_summary(), expected)

    def test_change_summary_when_detection_off(self):
        self.vm.set_detect_changes(False)
        self.assertEqual(self.vm._change_summary_text(), get_text("realtime_change_detection_off"))

    def test_change_summary_when_detection_on(self):
        self.vm.set_detect_changes(True)
        expected = get_text("realtime_changed_ids").format(changed=0, total=0)
        self.assertEqual(self.vm._change_summary_text(), expected)

    def test_change_summary_when_filtered(self):
        self.vm.set_detect_changes(True)
        self.vm.set_show_only_changing(True)
        expected = get_text("realtime_changed_ids_filtered").format(changed=0, total=0)
        self.assertEqual(self.vm._change_summary_text(), expected)


if __name__ == "__main__":
    unittest.main()
