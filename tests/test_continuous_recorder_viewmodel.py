from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from services.can_data_parser import frame_dict, rows_to_df
from viewmodels.continuous_recorder_viewmodel import ContinuousRecorderViewModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app: QApplication | None = None


def setUpModule() -> None:
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class ContinuousRecorderViewModelTests(unittest.TestCase):
    def test_worker_drains_queued_chunks_before_clean_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            vm = ContinuousRecorderViewModel()
            sizes = []
            vm.size_changed.connect(sizes.append)
            self.assertTrue(vm.start_recording(path))
            chunk = rows_to_df([frame_dict(ts=1.0, bus="can0", can_id=0x123, data=b"\x01")])
            deadline = time.monotonic() + 5
            while not vm.running and time.monotonic() < deadline:
                _app.processEvents()
                time.sleep(0.005)
            vm.append_chunk(chunk)
            vm.append_chunk(chunk.with_columns((chunk["TS"] + 1).alias("TS")))
            vm.stop_and_drain()
            _app.processEvents()
            self.assertGreaterEqual(len(sizes), 2)
            self.assertEqual(path.read_text(encoding="utf-8").count("#"), 2)
            self.assertIsNone(vm.active_path)

    def test_all_recording_paths_remain_available_for_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            vm = ContinuousRecorderViewModel()
            paths = [Path(directory) / f"capture-{index}.log" for index in range(2)]
            for path in paths:
                self.assertTrue(vm.start_recording(path))
                vm.stop_and_drain()
                _app.processEvents()
            self.assertEqual(vm.recorded_paths, tuple(str(path) for path in paths))


if __name__ == "__main__":
    unittest.main()
