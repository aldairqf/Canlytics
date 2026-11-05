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


class OfflineRealtimeViewModelTests(unittest.TestCase):
    def setUp(self):
        self.vm = RealTimeAnalysisViewModel()
        self.vm.set_enabled(True)

    def tearDown(self):
        self.vm.shutdown()

    def test_offline_cursor_emits_snapshot_and_can_step_by_timestamp(self):
        dataframe = rows_to_df([
            frame_dict(ts=1.0, bus="b", can_id="100", data=b"\x01"),
            frame_dict(ts=2.0, bus="b", can_id="100", data=b"\x02"),
            frame_dict(ts=2.5, bus="b", can_id="200", data=b"\x03"),
        ])
        self.vm.set_offline_dataframe(dataframe)
        self.assertTrue(self.vm._offline_threads[-1].wait(5000))
        QApplication.processEvents()
        self.assertEqual(self.vm.offline_frame_count, 3)
        self.vm.set_offline_timestamp(2.0)
        self.assertEqual(self.vm._df.filter(self.vm._df["ID"] == "100")["D0"].to_list(), [2])
        self.assertEqual(self.vm.offline_frame_index, 1)
        self.vm.set_offline_timestamp(2.5)
        self.assertEqual(set(self.vm._df["ID"].to_list()), {"100", "200"})

    def test_live_mode_invalidates_offline_index(self):
        self.vm.set_offline_dataframe(rows_to_df([
            frame_dict(ts=1.0, bus="b", can_id="100", data=b"\x01"),
        ]))
        self.assertTrue(self.vm._offline_threads[-1].wait(5000))
        QApplication.processEvents()
        self.vm.set_live_mode()
        self.assertFalse(self.vm.offline_mode)
        self.assertEqual(self.vm.offline_frame_count, 0)

    def test_offline_live_only_controls_do_not_clear_the_snapshot(self):
        self.vm.set_offline_dataframe(rows_to_df([
            frame_dict(ts=1.0, bus="b", can_id="100", data=b"\x01"),
            frame_dict(ts=2.0, bus="b", can_id="100", data=b"\x02"),
        ]))
        self.assertTrue(self.vm._offline_threads[-1].wait(5000))
        QApplication.processEvents()
        self.vm.set_offline_timestamp(2.0)
        self.vm.set_detect_changes(True)
        self.vm.set_show_only_changing(True)
        self.vm.reset_change_detection()
        self.assertEqual(self.vm._df["D0"].to_list(), [2])

    def test_disabling_realtime_releases_the_offline_index(self):
        self.vm.set_offline_dataframe(rows_to_df([
            frame_dict(ts=1.0, bus="b", can_id="100", data=b"\x01"),
        ]))
        self.assertTrue(self.vm._offline_threads[-1].wait(5000))
        QApplication.processEvents()
        self.vm.set_enabled(False)
        self.assertFalse(self.vm.offline_mode)
        self.assertEqual(self.vm.offline_frame_count, 0)


if __name__ == "__main__":
    unittest.main()
