"""Characterization tests for ConnectionStreamViewModel's last_kvaser_bitrate
tracking -- used to stamp saved logs with recording metadata (see
views/main_window.py::_save_current_log)."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtWidgets import QApplication

from viewmodels.connection_stream_viewmodel import ConnectionStreamViewModel

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class LastKvaserBitrateTests(unittest.TestCase):
    def setUp(self):
        self.vm = ConnectionStreamViewModel()

    def tearDown(self):
        self.vm.shutdown()

    def test_initially_none(self):
        self.assertIsNone(self.vm.last_kvaser_bitrate)

    def test_set_when_the_worker_resolves_a_bitrate(self):
        self.vm._on_kvaser_bitrate_resolved(500000)
        self.assertEqual(self.vm.last_kvaser_bitrate, 500000)

    def test_reset_when_a_new_connection_attempt_starts(self):
        # A prior Kvaser session's bitrate must not leak onto data recorded
        # by a subsequent, different-mode connection (e.g. SSH or replay).
        self.vm._on_kvaser_bitrate_resolved(500000)
        self.vm._start_worker({"mode": "replay", "path": "/nonexistent-path.log", "speed": 1.0})
        self.assertIsNone(self.vm.last_kvaser_bitrate)


if __name__ == "__main__":
    unittest.main()
