"""Characterization tests for ConnectionStreamViewModel's last_kvaser_bitrate
tracking -- used to stamp saved logs with recording metadata (see
views/main_window.py::_save_current_log)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from services.can_send import ResolvedFrame
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

    def test_is_replay_reflects_running_mode(self):
        self.assertFalse(self.vm.is_replay)

        self.vm._running = True
        self.vm._config = {"mode": "replay"}
        self.assertTrue(self.vm.is_replay)

        for mode in ("ssh", "kvaser"):
            self.vm._config = {"mode": mode}
            self.assertFalse(self.vm.is_replay)

        self.vm._running = False
        self.assertFalse(self.vm.is_replay)

    def test_initially_none(self):
        self.assertIsNone(self.vm.last_kvaser_bitrate)

    def test_set_when_the_worker_resolves_a_bitrate(self):
        self.vm._on_kvaser_bitrate_resolved(500000)
        self.assertEqual(self.vm.last_kvaser_bitrate, 500000)

    def test_reset_when_a_new_connection_attempt_starts(self):
        self.vm._on_kvaser_bitrate_resolved(500000)
        self.vm._start_worker({"mode": "replay", "path": "/nonexistent-path.log", "speed": 1.0})
        self.assertIsNone(self.vm.last_kvaser_bitrate)


class ReplayConnectionTests(unittest.TestCase):
    def setUp(self):
        self.vm = ConnectionStreamViewModel()

    def tearDown(self):
        self.vm.shutdown()

    def test_replay_streams_schema_chunks_and_stops_at_end_of_file(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "logs" / "candump-sample.log"
        chunks = []
        statuses: list[str] = []
        errors: list[str] = []
        self.vm.chunk_ready.connect(chunks.append)
        self.vm.status_changed.connect(statuses.append)
        self.vm.error.connect(errors.append)

        self.vm.start_replay(path=str(fixture), speed=10000.0, ts_offset=1.5)
        deadline = time.monotonic() + 5.0
        while self.vm.running and time.monotonic() < deadline:
            _app.processEvents()
            time.sleep(0.005)
        _app.processEvents()

        self.assertFalse(self.vm.running)
        self.assertFalse(errors, errors)
        self.assertTrue(chunks)
        self.assertTrue(any(status.startswith("Replay:") for status in statuses))
        frames = [frame for chunk in chunks for frame in chunk.iter_rows(named=True)]
        self.assertGreater(len(frames), 1)
        self.assertEqual(frames[0]["TS"], 1.5)
        self.assertEqual(set(frames[0]), {"TS", "Bus", "ID", "DATA", "LEN", *[f"D{i}" for i in range(8)]})


class QueuedSendDuringReceiveTests(unittest.TestCase):
    def setUp(self):
        self.vm = ConnectionStreamViewModel()

    def tearDown(self):
        self.vm.shutdown()

    def test_queued_send_is_processed_while_stream_runner_is_receiving(self):
        state = {"opened": False, "active": False, "sent_while_active": False, "finished": False}

        class FakeSource:
            bitrate = None

            @property
            def finished(self):
                return state["finished"]

            def open(self, *, canceled, status):
                state["opened"] = True
                state["active"] = True

            def receive(self, timeout):
                time.sleep(0.001)
                return None

            def send(self, frame):
                state["sent_while_active"] = state["active"]
                state["finished"] = True

            def close(self):
                state["active"] = False
                state["finished"] = True

        succeeded: list[str] = []
        self.vm.send_succeeded.connect(succeeded.append)
        with patch("viewmodels.connection_stream_viewmodel.create_can_source", return_value=FakeSource()):
            self.vm._start_worker({"mode": "kvaser", "poll_timeout": 0.01})
            deadline = time.monotonic() + 2.0
            while not state["opened"] and time.monotonic() < deadline:
                _app.processEvents()
                time.sleep(0.001)
            self.assertTrue(state["opened"])

            self.vm.request_send(ResolvedFrame("entry", 0x321, b"\x01", False))
            while self.vm.running and time.monotonic() < deadline:
                _app.processEvents()
                time.sleep(0.001)
            _app.processEvents()

        self.assertTrue(state["sent_while_active"])
        self.assertEqual(succeeded, ["entry"])

if __name__ == "__main__":
    unittest.main()
