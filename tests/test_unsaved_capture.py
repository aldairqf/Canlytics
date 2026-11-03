from __future__ import annotations

import sys
import unittest
import tempfile
import threading
import time
from pathlib import Path

import polars as pl
from PySide6.QtWidgets import QApplication

from services.can_data_parser import frame_dict, rows_to_df
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
            self.vm.append_df(rows_to_df([frame_dict(ts=2.0, bus="can0", can_id=0x100, data=b"\xBB")]))
            applied = []
            self.vm.normalize_applied.connect(applied.append)
            self.vm.set_normalize(True)
            self._wait_for(lambda: bool(applied))
        self.assertFalse(self.vm.has_unsaved_capture)
        self.assertEqual(self.vm.unsaved_capture_frame_count, 0)

    def test_normalize_parsing_runs_off_ui_thread_and_applies_on_ui_thread(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "logs" / "candump-sample.log"
        self.vm.load_log(str(fixture))
        worker_threads = []
        apply_threads = []
        applied = []
        original_load = self.vm._log.load

        def tracked_load(normalize_time=False):
            worker_threads.append(threading.current_thread())
            return original_load(normalize_time)

        self.vm._log.load = tracked_load
        self.vm.dataframe_replaced.connect(lambda _df: apply_threads.append(threading.current_thread()))
        self.vm.normalize_applied.connect(applied.append)
        self.vm.set_normalize(True)
        self._wait_for(lambda: bool(applied))

        self.assertIsNot(worker_threads[0], threading.main_thread())
        self.assertIs(apply_threads[-1], threading.main_thread())
        self.assertEqual(applied, [True])
        self.assertEqual(self.vm.df["TS"][0], 0.0)

    def test_normalize_result_does_not_overwrite_data_appended_while_worker_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_text("(1.0) can0 100#AA\n", encoding="utf-8")
            self.vm.load_log(str(path))
            started = threading.Event()
            release = threading.Event()
            original_load = self.vm._log.load

            def delayed_load(normalize_time=False):
                started.set()
                release.wait(2.0)
                return original_load(normalize_time)

            self.vm._log.load = delayed_load
            failures = []
            self.vm.normalize_failed.connect(lambda message, previous: failures.append((message, previous)))
            self.vm.set_normalize(True)
            self._wait_for(started.is_set)
            self.assertFalse(self.vm.normalize)
            self.vm.append_df(rows_to_df([frame_dict(ts=2.0, bus="can0", can_id=0x100, data=b"\xBB")]))
            self.vm.flush_pending()
            release.set()
            self._wait_for(lambda: bool(failures))

        self.assertEqual(self.vm.df["TS"].to_list(), [1.0, 2.0])
        self.assertFalse(self.vm.normalize)
        self.assertIn("Data changed", failures[0][0])

    def test_normalize_failure_keeps_previous_dataframe_and_mode(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "logs" / "candump-sample.log"
        self.vm.load_log(str(fixture))
        previous = self.vm.df
        failures = []

        def fail_load(normalize_time=False):
            raise OSError("read failed")

        self.vm._log.load = fail_load
        self.vm.normalize_failed.connect(lambda message, mode: failures.append((message, mode)))
        self.vm.set_normalize(True)
        self._wait_for(lambda: bool(failures))

        self.assertIs(self.vm.df, previous)
        self.assertFalse(self.vm.normalize)
        self.assertEqual(failures, [("read failed", False)])

    def test_clear_during_normalize_then_load_does_not_leave_pending_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.log"
            second = Path(directory) / "second.log"
            first.write_text("(1.0) can0 100#AA\n", encoding="utf-8")
            second.write_text("(10.0) can0 100#BB\n", encoding="utf-8")
            self.vm.load_log(str(first))
            started = threading.Event()
            release = threading.Event()
            original_load = self.vm._log.load

            def delayed_load(normalize_time=False):
                started.set()
                release.wait(2.0)
                return original_load(normalize_time)

            self.vm._log.load = delayed_load
            self.vm.set_normalize(True)
            self._wait_for(started.is_set)
            self.vm.clear()
            self.vm.load_log(str(second))
            release.set()
            self._wait_for(lambda: self.vm._normalize_worker is None)

        self.assertEqual(self.vm.df["TS"].to_list(), [10.0])
        self.assertFalse(self.vm.normalize)
        self.assertFalse(self.vm._normalize_requested)

    def _wait_for(self, predicate):
        deadline = time.monotonic() + 3.0
        while not predicate() and time.monotonic() < deadline:
            _app.processEvents()
            time.sleep(0.005)
        _app.processEvents()
        self.assertTrue(predicate(), "condition was not reached before timeout")

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
