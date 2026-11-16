from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from models.mux_config import MuxConfigEntry
from services.session_state import SessionStateStore
from viewmodels.mux_detection_viewmodel import MuxDetectionViewModel
from viewmodels.mux_detection_worker import MuxDetectionWorker
from services.mux_detector import MuxDetectorConfig
from viewmodels.mux_configuration_viewmodel import MuxConfigurationViewModel
from views.mux_detection_window import MuxDetectionWindow
from tests.test_mux_detector import synthetic_mux
from config.app_config import get_text
from config.theme import apply_theme, get_theme


class MuxDetectionViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SessionStateStore(root=Path(self.temp.name))
        self.shared = MuxConfigurationViewModel(self.store)
        self.vm = MuxDetectionViewModel(self.shared)
        self.addCleanup(self.vm.shutdown)

    def test_mux_ui_texts_are_english(self):
        expected = {
            "mux_only_with_mux": "Only IDs with mux",
            "mux_result_empty_intro": "Select Detect mux to find bytes that identify message states.",
            "mux_result_empty_none": "No multiplexed IDs were found with the available evidence.",
            "mux_summary": "{muxed} of {total} IDs look multiplexed",
            "mux_applied": "Applied",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(get_text(key), value)

    def test_apply_persists_shared_wildcard_mux(self):
        self.vm._results = [{"can_id": "123", "selector": (1, 2), "has_mux": True}]
        self.assertFalse(self.vm.apply_result("123"))
        self.assertEqual(self.shared.configs, [MuxConfigEntry("123", None, (1, 2))])

    def test_apply_replaces_conflicting_wildcard_and_reports_it(self):
        self.shared.set_configuration([MuxConfigEntry("123", None, (0,))])
        self.vm._results = [{"can_id": "123", "selector": (1,), "has_mux": True}]
        self.assertTrue(self.vm.apply_result("123"))
        self.assertEqual(self.shared.configs, [MuxConfigEntry("123", None, (1,))])

    def test_cancelled_worker_returns_without_scanning_ids(self):
        worker = MuxDetectionWorker(df=pl.DataFrame({"ID": ["123"], "LEN": [1], "TS": [0.0], **{f"D{i}": [0] for i in range(8)}}), can_ids=None, config=MuxDetectorConfig())
        worker.cancel()
        results = []
        worker.finished.connect(results.append)
        worker.run()
        self.assertEqual(results, [[]])


    def test_excluded_values_block_shared_configuration_application(self):
        self.vm._results = [{"can_id": "123", "selector": (1,), "has_mux": True,
                             "excluded_values": ["02"]}]
        blocked = []
        self.vm.configuration_apply_blocked.connect(blocked.append)
        self.assertFalse(self.vm.apply_result("123"))
        self.assertEqual(blocked, ["123"])
        self.assertEqual(self.shared.configs, [])

    def test_worker_recalculates_a_forced_selector(self):
        results = []
        worker = MuxDetectionWorker(df=synthetic_mux(ids=3, frames=2400), can_ids=["000"],
                                   config=MuxDetectorConfig(), forced_selectors={"000": (1, 2)})
        worker.finished.connect(results.append)
        worker.run()
        self.assertEqual(results[0][0]["selector"], (1, 2))

    def test_selector_recalculation_preserves_valid_exclusions(self):
        self.vm._results = [{"can_id": "000", "selector": (0,), "excluded_values": ["02"]}]
        self.vm._replacement_id = "000"
        self.vm._on_finished([{"can_id": "000", "selector": (1,), "values": [{"value": "02"}]}])
        self.assertEqual(self.vm.results[0]["excluded_values"], ["02"])

    def test_window_constructs_offscreen_and_deletes_on_close(self):
        window = MuxDetectionWindow(self.vm)
        self.assertTrue(window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))
        window.close()

    def test_simple_results_default_to_mux_table_and_preselect_first_mux(self):
        window = MuxDetectionWindow(self.vm)
        self.assertTrue(window.only_mux.isChecked())
        self.assertEqual(window.results.columnCount(), 5)
        self.assertFalse(window.empty_state.isHidden())
        self.assertIn(get_text("mux_result_empty_intro"), window.empty_state.text())
        self.assertFalse(window.apply_button.isEnabled())
        self.assertFalse(window.candidate_button.isEnabled())

        no_mux = {"can_id": "100", "selector": (), "values": [], "has_mux": False,
                  "confidence": None, "discarded": {}}
        mux = {"can_id": "200", "selector": (1,), "values": [{"value": "01", "n": 5,
               "period_median": 0.02, "cv": 0.0, "dlc": 8}], "has_mux": True,
               "confidence": "medium", "discarded": {}}
        self.vm._results = [no_mux, mux]
        window._on_results_changed([no_mux, mux])

        self.assertEqual(window.results.rowCount(), 1)
        self.assertEqual(window.results.item(window.results.currentRow(), 0).text(), "200")
        self.assertEqual(window.summary.text(), get_text("mux_summary").format(muxed=1, total=2))
        self.assertTrue(window.apply_button.isEnabled())
        self.assertTrue(window.selector_chips_layout.itemAt(0).widget().isEnabled())
        self.assertIn("ID 200", window.discard_reasons.text())
        self.assertTrue(window.values.cellWidget(0, 0).isChecked())
        self.assertEqual(window.values.item(0, 2).text(), "5")
        self.assertEqual(window.values.item(0, 3).text(), "20.000")

        window.only_mux.setChecked(False)
        no_mux_row = next(row for row in range(window.results.rowCount())
                          if window.results.item(row, 0).text() == "100")
        window.results.setCurrentCell(no_mux_row, 0)
        self.assertFalse(window.apply_button.isEnabled())
        self.assertFalse(window.candidate_button.isEnabled())
        self.assertIsNone(no_mux["confidence"])
        window.close()

    def test_applied_badge_persists_and_confidence_badge_tracks_theme(self):
        result = {"can_id": "200", "selector": (1,), "values": [], "has_mux": True,
                  "confidence": "high", "discarded": {}}
        self.vm._results = [result]
        apply_theme(self.app, "Dark")
        self.addCleanup(lambda: apply_theme(self.app, "Dark"))
        window = MuxDetectionWindow(self.vm)
        window.show()
        self.app.processEvents()
        window._on_results_changed([result])
        self.assertIn(get_theme("Dark").success, window.results.cellWidget(0, 3).styleSheet())

        apply_theme(self.app, "Light")
        self.app.processEvents()
        self.assertIn(get_theme("Light").success, window.results.cellWidget(0, 3).styleSheet())
        apply_theme(self.app, "Dark")

        window.apply_button.click()
        status = window.results.cellWidget(0, 4)
        self.assertTrue(status.property("applied"))
        self.assertEqual(status.text(), get_text("mux_applied"))
        window.close()

        reopened = MuxDetectionWindow(self.vm)
        reopened._on_results_changed([result])
        self.assertTrue(reopened.results.cellWidget(0, 4).property("applied"))
        self.assertEqual(reopened.results.cellWidget(0, 4).text(), get_text("mux_applied"))
        reopened.close()

    def test_candidate_action_reads_selected_result_from_any_table_column(self):
        from unittest.mock import Mock

        manager = Mock()
        window = MuxDetectionWindow(self.vm, candidate_manager=manager)
        result = {"can_id": "200", "selector": (1,), "values": [], "has_mux": True,
                  "confidence": "medium", "discarded": {}}
        self.vm._results = [result]
        window._on_results_changed([result])
        window.results.setCurrentCell(0, 1)

        window._open_candidate()

        manager.open_window_for_can_id.assert_called_once_with("200", source="Mux Detection")
        window.close()


if __name__ == "__main__":
    unittest.main()
