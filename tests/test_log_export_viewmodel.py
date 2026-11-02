from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import polars as pl
from PySide6.QtWidgets import QApplication

from services.can_data_parser import frame_dict, rows_to_df
from viewmodels.data_viewmodel import LogDataViewModel
from viewmodels.log_export_viewmodel import LogExportViewModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app: QApplication | None = None


def setUpModule() -> None:
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class LogExportViewModelTests(unittest.TestCase):
    def _wait_for(self, vm: LogExportViewModel) -> None:
        deadline = time.monotonic() + 10.0
        while vm.running and time.monotonic() < deadline:
            vm.wait(10)
            _app.processEvents()
        vm.wait(2_000)
        _app.processEvents()
        self.assertFalse(vm.running, "export worker did not finish")

    def test_worker_reports_progress_and_finishes_export(self):
        frame = frame_dict(ts=1_700_000_000.0, bus="can0", can_id=0x123, data=b"\x01")
        vm = LogExportViewModel()
        progress = []
        vm.progress_changed.connect(lambda done, total: progress.append((done, total)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            self.assertTrue(vm.start_export(rows_to_df([frame]), path))
            self._wait_for(vm)
            self.assertEqual(vm.result_path, str(path))
            self.assertEqual(progress[-1], (1, 1))
            self.assertTrue(path.is_file())

    def test_cancel_stops_worker_and_preserves_destination(self):
        count = 40_000
        dataframe = pl.DataFrame({
            "TS": [1_700_000_000.0 + i / 1000 for i in range(count)],
            "Bus": ["can0"] * count,
            "ID": ["123"] * count,
            "DATA": ["01"] * count,
        })
        vm = LogExportViewModel()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_bytes(b"previous")
            self.assertTrue(vm.start_export(dataframe, path))
            vm.cancel()
            self._wait_for(vm)
            self.assertTrue(vm.was_canceled)
            self.assertEqual(path.read_bytes(), b"previous")

    def test_saved_state_is_not_cleared_if_capture_changed_during_export(self):
        data_vm = LogDataViewModel()
        data_vm.append_df(pl.DataFrame({"TS": [1.0]}))
        snapshot_revision = data_vm.data_revision
        data_vm.append_df(pl.DataFrame({"TS": [2.0]}))
        self.assertFalse(data_vm.mark_capture_saved(expected_revision=snapshot_revision))
        self.assertTrue(data_vm.has_unsaved_capture)
        self.assertTrue(data_vm.mark_capture_saved(expected_revision=data_vm.data_revision))
        self.assertFalse(data_vm.has_unsaved_capture)

    def test_data_viewmodel_tracks_loaded_and_appended_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.log"
            second = Path(directory) / "second.log"
            first.write_text("(1.0) can0 100#AA\n", encoding="utf-8")
            second.write_text("(2.0) can0 101#BB\n", encoding="utf-8")
            data_vm = LogDataViewModel()
            data_vm.load_log(str(first))
            data_vm.append_log(str(second))
            self.assertEqual(set(data_vm.source_paths), {str(first.resolve()), str(second.resolve())})
            data_vm.clear()
            self.assertEqual(data_vm.source_paths, ())


if __name__ == "__main__":
    unittest.main()
