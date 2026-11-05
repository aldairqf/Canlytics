from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from PySide6.QtCore import QCoreApplication

from models.analysis_context import AnalysisMarker
from services.event_markers import (
    append_event_marker,
    build_event_comparisons,
    session_marker_key,
)
from services.session_state import SessionStateStore
from viewmodels.event_markers_viewmodel import EventMarkersViewModel


class EventMarkerValidationTests(unittest.TestCase):
    def test_appends_named_on_off_markers_with_stable_sequence(self):
        markers = append_event_marker((), "Hydraulics", "ON", 10.0)
        markers = append_event_marker(markers, "Hydraulics", "off", 20.0)

        self.assertEqual(markers, (
            AnalysisMarker(1, "Hydraulics", 10.0, "ON"),
            AnalysisMarker(2, "Hydraulics", 20.0, "OFF"),
        ))

    def test_rejects_blank_or_long_names_invalid_states_and_nonfinite_timestamps(self):
        for name, state, timestamp in (
            ("  ", "ON", 1.0), ("x" * 121, "ON", 1.0),
            ("event", "ACTIVE", 1.0), ("event", "ON", float("inf")),
        ):
            with self.subTest(name=name, state=state, timestamp=timestamp):
                with self.assertRaises(ValueError):
                    append_event_marker((), name, state, timestamp)


class EventComparisonTests(unittest.TestCase):
    def test_pairs_latest_on_off_of_same_name_and_builds_baseline(self):
        markers = (
            AnalysisMarker(1, "boom", 10.0, "ON"),
            AnalysisMarker(2, "other", 12.0, "ON"),
            AnalysisMarker(3, "boom", 15.0, "OFF"),
            AnalysisMarker(4, "boom", 30.0, "ON"),
            AnalysisMarker(5, "boom", 36.0, "OFF"),
        )

        comparisons = build_event_comparisons(markers, log_start=0.0, log_end=40.0)

        self.assertEqual(len(comparisons), 2)
        self.assertEqual(comparisons[-1].name, "boom")
        self.assertEqual(comparisons[-1].range_b, (30.0, 36.0))
        self.assertLess(comparisons[-1].range_a[1], 30.0)
        self.assertAlmostEqual(comparisons[-1].range_a[0], 24.0)

    def test_clips_baseline_to_log_start(self):
        markers = (AnalysisMarker(1, "lift", 5.0, "ON"), AnalysisMarker(2, "lift", 15.0, "OFF"))
        comparisons = build_event_comparisons(markers, log_start=0.0, log_end=20.0)

        self.assertEqual(comparisons[0].range_a[0], 0.0)
        self.assertLess(comparisons[0].range_a[1], 5.0)
        self.assertEqual(comparisons[0].range_b, (5.0, 15.0))

    def test_does_not_propose_unmatched_or_baseline_free_events(self):
        unmatched = (AnalysisMarker(1, "a", 5.0, "ON"),)
        baseline_free = (AnalysisMarker(1, "a", 0.0, "ON"), AnalysisMarker(2, "a", 5.0, "OFF"))

        self.assertEqual(build_event_comparisons(unmatched, log_start=0.0, log_end=10.0), ())
        self.assertEqual(build_event_comparisons(baseline_free, log_start=0.0, log_end=10.0), ())

    def test_source_key_is_independent_of_order_and_path_case(self):
        self.assertEqual(
            session_marker_key((r"C:\logs\a.log", r"C:\logs\b.log")),
            session_marker_key((r"c:\logs\B.log", r"c:\logs\A.log")),
        )
        self.assertEqual(session_marker_key(()), "")


class EventMarkersViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = SessionStateStore(root=Path(self._tmp.name) / "state")
        self.vm = EventMarkersViewModel(self.store)

    def test_persists_markers_and_isolates_other_source_sessions(self):
        self.vm.set_session_sources((str(Path(self._tmp.name) / "a.log"),))
        self.vm.add_marker("lift", "ON", 4.0)
        saved_key = self.vm.session_key

        self.vm.set_session_sources((str(Path(self._tmp.name) / "b.log"),))

        self.assertNotEqual(self.vm.session_key, saved_key)
        self.assertEqual(self.vm.markers, ())
        self.vm.set_session_sources((str(Path(self._tmp.name) / "a.log"),))
        self.assertEqual(self.vm.markers[0].name, "lift")

    def test_appending_a_source_carries_markers_into_the_combined_session(self):
        a = str(Path(self._tmp.name) / "a.log")
        b = str(Path(self._tmp.name) / "b.log")
        self.vm.set_session_sources((a,))
        self.vm.add_marker("boom", "ON", 8.0)

        self.vm.set_session_sources((a, b))

        self.assertEqual(len(self.vm.markers), 1)
        self.assertTrue(self.store.get_event_markers(self.vm.session_key))

    def test_context_marker_provider_exports_persisted_state_values(self):
        self.vm.set_session_sources((str(Path(self._tmp.name) / "a.log"),))
        self.vm.add_marker("boom", "OFF", 9.0)

        self.assertEqual(self.vm.context_markers(), ({
            "sequence": 1, "name": "boom", "timestamp": 9.0, "state": "OFF",
        },))

    def test_shifts_marker_timestamps_and_persists_after_time_normalization(self):
        source = str(Path(self._tmp.name) / "a.log")
        self.vm.set_session_sources((source,))
        self.vm.add_marker("pump", "ON", 100.0)
        self.vm.shift_timestamps(-100.0)
        self.assertEqual(self.vm.markers[0].timestamp, 0.0)
        self.assertEqual(self.store.get_event_markers(self.vm.session_key)[0]["timestamp"], 0.0)

    def test_clear_markers_resets_the_current_recording_session(self):
        self.vm.set_session_sources((str(Path(self._tmp.name) / "capture.log"),))
        self.vm.add_marker("pump", "ON", 100.0)
        self.vm.clear_markers()
        self.assertEqual(self.vm.markers, ())
        self.assertEqual(self.store.get_event_markers(self.vm.session_key), [])

    def test_cannot_add_marker_without_a_loaded_or_recording_session(self):
        with self.assertRaises(ValueError):
            self.vm.add_marker("boom", "ON", 9.0)


if __name__ == "__main__":
    unittest.main()
