from __future__ import annotations

import ast
import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from config.defaults import DEFAULT_OPTIONS
from services.candidate_tag_migration import legacy_candidate_tag_to_signal
from services.session_state import SessionStateStore
from viewmodels.main_window_viewmodel import MainWindowViewModel


ROOT = Path(__file__).resolve().parents[1]


class U14DefaultsTests(unittest.TestCase):
    def test_candidate_max_length_defaults_to_sixteen(self):
        self.assertEqual(DEFAULT_OPTIONS["candidate_max_length"], 16)
        source = (ROOT / "views/candidate_interpretations_window.py").read_text(encoding="utf-8")
        self.assertIn('get_option("candidate_max_length", 16)', source)


class U14XYModeTests(unittest.TestCase):
    def test_xy_is_embedded_in_plot_without_standalone_window(self):
        plot_source = (ROOT / "views/plot/plot_window.py").read_text(encoding="utf-8")
        ribbon_source = (ROOT / "views/plot/plot_ribbon.py").read_text(encoding="utf-8")
        self.assertIn("from views.plot.xy_plot_widget import XYPlotWidget", plot_source)
        self.assertNotIn("XYWindow", plot_source)
        self.assertNotIn("view_xy", ribbon_source)
        self.assertFalse((ROOT / "views/plot/xy_window.py").exists())
        module = ast.parse((ROOT / "views/plot/xy_plot_widget.py").read_text(encoding="utf-8"))
        self.assertIn("XYPlotWidget", {node.name for node in module.body if isinstance(node, ast.ClassDef)})


class U14CandidateTagMigrationTests(unittest.TestCase):
    def test_legacy_tags_convert_to_working_signal_parameters(self):
        signal = legacy_candidate_tag_to_signal(
            "ID: 0CF00400 LEN: 8 MUX: All startBit: 24 sigLen: 16 Unsigned LittleEndian",
            "EngineSpeed",
        )
        self.assertEqual(signal["can_id"], "0CF00400")
        self.assertEqual(signal["start"], 24)
        self.assertEqual(signal["length"], 16)
        self.assertEqual(signal["byte_order"], "little_endian")
        self.assertEqual(signal["signal_name"], "EngineSpeed")

    def test_unparseable_legacy_tags_are_left_out_of_migration(self):
        self.assertIsNone(legacy_candidate_tag_to_signal("legacy label", "EngineSpeed"))

    def test_migration_runs_once_and_keeps_the_legacy_file(self):
        with tempfile.TemporaryDirectory() as directory:
            state = SessionStateStore(Path(directory))
            state.signal_tags_path.write_text(json.dumps({
                "ID: 0CF00400 LEN: 8 MUX: All startBit: 24 sigLen: 16 Unsigned LittleEndian": "EngineSpeed"
            }), encoding="utf-8")
            fake = SimpleNamespace(session_state=state, save_working_signal=Mock())
            MainWindowViewModel._migrate_candidate_tags(fake)
            MainWindowViewModel._migrate_candidate_tags(fake)
            fake.save_working_signal.assert_called_once()
            self.assertTrue(state.signal_tags_path.exists())
            self.assertTrue(state.get_window_prefs("candidate_tags_migration")["working_dbc_migrated"])


if __name__ == "__main__":
    unittest.main()
