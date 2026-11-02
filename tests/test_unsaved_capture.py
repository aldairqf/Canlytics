from __future__ import annotations

import sys
import unittest
import tempfile
from pathlib import Path

import polars as pl
from PySide6.QtWidgets import QApplication

from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.main_window_viewmodel import unsaved_prompt_kind, new_session_prompt_kind
from utils.capture_save import save_capture_sequence

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class UnsavedCaptureTests(unittest.TestCase):
    def setUp(self):
        self.vm = LogDataViewModel()

    def test_capture_append_marks_unsaved_immediately(self):
        self.vm.append_df(pl.DataFrame({"TS": [1.0]}))
        self.assertTrue(self.vm.has_unsaved_capture)
        self.assertEqual(self.vm.unsaved_capture_frame_count, 1)

    def test_loaded_log_starts_saved(self):
        with tempfile.NamedTemporaryFile() as handle:
            self.vm.replace_log(handle.name, pl.DataFrame({"TS": [1.0]}))
        self.assertFalse(self.vm.has_unsaved_capture)

    def test_successful_save_marks_capture_saved(self):
        self.vm.append_df(pl.DataFrame({"TS": [1.0]}))
        self.vm.mark_capture_saved()
        self.assertFalse(self.vm.has_unsaved_capture)
        self.assertEqual(self.vm.unsaved_capture_frame_count, 0)

    def test_clear_marks_capture_saved(self):
        self.vm.append_df(pl.DataFrame({"TS": [1.0]}))
        self.vm.clear()
        self.assertFalse(self.vm.has_unsaved_capture)

    def test_prompt_kind_covers_empty_saved_and_unsaved_data(self):
        self.assertEqual(unsaved_prompt_kind(False, False), "none")
        self.assertEqual(unsaved_prompt_kind(True, False), "confirm")
        self.assertEqual(unsaved_prompt_kind(True, True), "save_discard_cancel")

    def test_manual_new_session_prompt_only_depends_on_unsaved_capture(self):
        self.assertEqual(new_session_prompt_kind(False), "none")
        self.assertEqual(new_session_prompt_kind(True), "save_discard_append_cancel")

    def test_append_from_file_does_not_mark_capture_unsaved(self):
        self.vm.append_df(pl.DataFrame({"TS": [1.0]}), unsaved=False)
        self.assertFalse(self.vm.has_unsaved_capture)

    def test_normalize_reload_clears_unsaved_pending_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_text("(1.0) can0 100#AA\n", encoding="utf-8")
            self.vm.load_log(str(path))
            self.vm.append_df(pl.DataFrame({"TS": [2.0]}))
            self.vm.set_normalize(True)
        self.assertFalse(self.vm.has_unsaved_capture)
        self.assertEqual(self.vm.unsaved_capture_frame_count, 0)

    def test_save_flushes_chunks_arriving_during_path_dialog_before_snapshot(self):
        self.vm.append_df(pl.DataFrame({"TS": [1.0]}))
        order = []
        written = []

        def choose_path():
            order.append("path")
            self.vm.append_df(pl.DataFrame({"TS": [2.0]}))
            return "capture.log"

        def write_snapshot(path, snapshot):
            order.append("write")
            written.extend(snapshot["TS"].to_list())

        saved_path = save_capture_sequence(self.vm, choose_path, write_snapshot)
        self.assertEqual(saved_path, "capture.log")
        self.assertEqual(order, ["path", "write"])
        self.assertEqual(written, [1.0, 2.0])
        self.assertFalse(self.vm.has_unsaved_capture)

    def test_save_drains_worker_chunks_before_flushing_and_snapshot(self):
        self.vm.append_df(pl.DataFrame({"TS": [1.0]}))
        written = []

        def stop_and_drain():
            self.vm.append_df(pl.DataFrame({"TS": [2.0]}))

        saved_path = save_capture_sequence(
            self.vm,
            lambda: "capture.log",
            lambda _path, snapshot: written.extend(snapshot["TS"].to_list()),
            stop_capture=stop_and_drain,
        )
        self.assertEqual(saved_path, "capture.log")
        self.assertEqual(written, [1.0, 2.0])
        self.assertFalse(self.vm.has_unsaved_capture)


if __name__ == "__main__":
    unittest.main()
