"""Characterization tests for RealTimeAnalysisViewModel's CAN-id index upkeep."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtWidgets import QApplication

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


if __name__ == "__main__":
    unittest.main()
