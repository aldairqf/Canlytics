"""Characterization tests for _ConnectionStreamWorker._stream_lines' disconnect detection."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from services.can_data_parser import StreamCanParser
from viewmodels.connection_stream_viewmodel import _ConnectionStreamWorker

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


def _worker() -> _ConnectionStreamWorker:
    return _ConnectionStreamWorker({"mode": "ssh"})


class ExitStatusReadyTests(unittest.TestCase):
    def test_raises_when_remote_command_already_exited(self):
        worker = _worker()
        worker._channel = MagicMock(closed=False, exit_status_ready=lambda: True)
        with self.assertRaisesRegex(ConnectionError, "exited"):
            worker._stream_lines(StreamCanParser())


class EofDetectionTests(unittest.TestCase):
    def test_raises_on_empty_recv(self):
        worker = _worker()
        channel = MagicMock(closed=False, exit_status_ready=lambda: False)
        channel.recv_ready.return_value = True
        channel.recv.return_value = b""
        worker._channel = channel
        with self.assertRaisesRegex(ConnectionError, "closed by remote"):
            worker._stream_lines(StreamCanParser())


class IdlePingWatchdogTests(unittest.TestCase):
    def _idle_channel(self) -> MagicMock:
        channel = MagicMock(closed=False, exit_status_ready=lambda: False)
        channel.recv_ready.return_value = False
        return channel

    def test_ping_success_keeps_streaming(self):
        worker = _worker()
        worker._IDLE_PING_SECONDS = 0.02
        worker._channel = self._idle_channel()

        calls = {"n": 0}

        def fake_ping():
            calls["n"] += 1
            if calls["n"] >= 2:
                worker._stop = True  # end the test once we've proven ping() ran
            return True

        worker._conn = MagicMock(ping=fake_ping)
        worker._stream_lines(StreamCanParser())  # must not raise
        self.assertGreaterEqual(calls["n"], 2)

    def test_ping_failure_raises_connection_lost(self):
        worker = _worker()
        worker._IDLE_PING_SECONDS = 0.02
        worker._channel = self._idle_channel()
        worker._conn = MagicMock(ping=lambda: False)
        with self.assertRaisesRegex(ConnectionError, "no response"):
            worker._stream_lines(StreamCanParser())


if __name__ == "__main__":
    unittest.main()
