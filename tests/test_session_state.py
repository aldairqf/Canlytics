"""Characterization tests for services/session_state.py's debug-mode persistence
(Debug Mode/Logging, Phase 2) -- same get/set/round-trip pattern as get_theme/set_theme."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from models.mux_config import MuxConfigEntry
from services.session_state import SessionStateStore


class DebugModePersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = SessionStateStore(root=Path(self._tmp.name))

    def test_defaults_to_disabled(self):
        self.assertFalse(self.store.get_debug_mode())

    def test_round_trips_enabled(self):
        self.store.set_debug_mode(True)
        self.assertTrue(self.store.get_debug_mode())

    def test_round_trips_disabled_after_enabling(self):
        self.store.set_debug_mode(True)
        self.store.set_debug_mode(False)
        self.assertFalse(self.store.get_debug_mode())

    def test_persists_across_separate_store_instances(self):
        self.store.set_debug_mode(True)
        reloaded = SessionStateStore(root=Path(self._tmp.name))
        self.assertTrue(reloaded.get_debug_mode())

    def test_root_property_matches_constructor_argument(self):
        self.assertEqual(self.store.root, Path(self._tmp.name))


class WindowPrefsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = SessionStateStore(root=Path(self._tmp.name))

    def test_missing_key_returns_empty_dict(self):
        self.assertEqual(self.store.get_window_prefs("candidate_interpretations"), {})

    def test_round_trips_prefs(self):
        self.store.set_window_prefs("candidate_interpretations", {"min_length": 8, "max_length": 16})
        self.assertEqual(
            self.store.get_window_prefs("candidate_interpretations"),
            {"min_length": 8, "max_length": 16},
        )

    def test_different_window_keys_are_independent(self):
        self.store.set_window_prefs("candidate_interpretations", {"min_length": 8})
        self.store.set_window_prefs("diff_analyzer", {"ignore_counters": True})
        self.assertEqual(self.store.get_window_prefs("candidate_interpretations"), {"min_length": 8})
        self.assertEqual(self.store.get_window_prefs("diff_analyzer"), {"ignore_counters": True})

    def test_persists_across_separate_store_instances(self):
        self.store.set_window_prefs("candidate_interpretations", {"min_length": 8})
        reloaded = SessionStateStore(root=Path(self._tmp.name))
        self.assertEqual(reloaded.get_window_prefs("candidate_interpretations"), {"min_length": 8})

    def test_set_overwrites_the_whole_bag_not_a_merge(self):
        self.store.set_window_prefs("candidate_interpretations", {"min_length": 8, "max_length": 16})
        self.store.set_window_prefs("candidate_interpretations", {"granularity": 4})
        self.assertEqual(self.store.get_window_prefs("candidate_interpretations"), {"granularity": 4})


class MuxConfigurationPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = SessionStateStore(root=Path(self._tmp.name))

    def test_defaults_to_empty(self) -> None:
        self.assertEqual(self.store.get_mux_configuration(), [])

    def test_round_trips_and_normalizes_entries(self) -> None:
        self.store.set_mux_configuration([
            MuxConfigEntry(can_id="100", length=8, mux_bytes=(2, 0, 2)),
        ])

        self.assertEqual(
            self.store.get_mux_configuration(),
            [MuxConfigEntry(can_id="100", length=8, mux_bytes=(0, 2))],
        )

    def test_preserves_other_session_fields(self) -> None:
        self.store.set_theme("dark")
        self.store.set_mux_configuration([MuxConfigEntry(can_id="18FEF100", length=None, mux_bytes=(0,))])

        self.assertEqual(self.store.get_theme(), "dark")
        self.assertEqual(self.store.get_mux_configuration()[0].can_id, "18FEF100")

    def test_ignores_invalid_saved_entries(self) -> None:
        self.store._state_path.parent.mkdir(parents=True, exist_ok=True)
        self.store._state_path.write_text(
            '{"mux_configuration": ['
            '{"can_id":"100","length":8,"mux_bytes":[0]},'
            '{"can_id":"100","length":8,"mux_bytes":[1]},'
            '{"can_id":"not-hex","length":8,"mux_bytes":[0]},'
            '{"can_id":"101","length":1,"mux_bytes":[2]}]}'
        )

        self.assertEqual(
            self.store.get_mux_configuration(),
            [MuxConfigEntry(can_id="100", length=8, mux_bytes=(0,))],
        )

    def test_ignores_non_finite_saved_integers(self) -> None:
        self.store._state_path.parent.mkdir(parents=True, exist_ok=True)
        self.store._state_path.write_text(
            '{"mux_configuration": ['
            '{"can_id":"100","length":1e999,"mux_bytes":[0]},'
            '{"can_id":"101","length":8,"mux_bytes":[1e999]},'
            '{"can_id":"102","length":1.5,"mux_bytes":[0]},'
            '{"can_id":"103","length":8,"mux_bytes":[1.5]}]}'
        )

        self.assertEqual(self.store.get_mux_configuration(), [])


if __name__ == "__main__":
    unittest.main()
