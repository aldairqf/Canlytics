from __future__ import annotations

import unittest

from viewmodels.main_window_viewmodel import build_active_source_presentation


class ActiveSourcePresentationTests(unittest.TestCase):
    def test_empty_session(self) -> None:
        presentation = build_active_source_presentation((), "offline", False)
        self.assertEqual((presentation.kind, presentation.label, presentation.paths), ("none", "Sin fuente", ()))

    def test_single_log_uses_filename(self) -> None:
        presentation = build_active_source_presentation(("C:/logs/drive.asc",), "offline", False)
        self.assertEqual(presentation.kind, "log")
        self.assertEqual(presentation.label, "drive.asc")

    def test_multiple_sources_and_unsaved_state(self) -> None:
        presentation = build_active_source_presentation(("a.asc", "b.blf"), "offline", True)
        self.assertEqual(presentation.kind, "multiple")
        self.assertEqual(presentation.label, "2 archivos")
        self.assertTrue(presentation.unsaved)

    def test_replay_and_live_modes_are_preserved(self) -> None:
        self.assertEqual(build_active_source_presentation(("a.asc",), "replay", False).kind, "replay")
        self.assertEqual(build_active_source_presentation((), "kvaser", True).kind, "kvaser")
        self.assertEqual(build_active_source_presentation((), "ssh", True).kind, "ssh")


if __name__ == "__main__":
    unittest.main()
