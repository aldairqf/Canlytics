"""Characterization tests for SSH source disconnect detection."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from services.can_data_parser import StreamCanParser
from services.can_sources import SshCanSource


def _source() -> SshCanSource:
    source = SshCanSource({"host": "device", "username": "user", "iface": "can0"})
    source._last_activity = time.monotonic()
    return source


class ExitStatusReadyTests(unittest.TestCase):
    def test_raises_when_remote_command_already_exited(self):
        source = _source()
        source._channel = MagicMock(closed=False, exit_status_ready=lambda: True)
        with self.assertRaisesRegex(ConnectionError, "exited"):
            source.receive(0.1)


class EofDetectionTests(unittest.TestCase):
    def test_raises_on_empty_recv(self):
        source = _source()
        channel = MagicMock(closed=False, exit_status_ready=lambda: False)
        channel.recv_ready.return_value = True
        channel.recv.return_value = b""
        source._channel = channel
        source._parser = StreamCanParser()
        with self.assertRaisesRegex(ConnectionError, "closed by remote"):
            source.receive(0.1)


class IdlePingWatchdogTests(unittest.TestCase):
    def _idle_channel(self) -> MagicMock:
        channel = MagicMock(closed=False, exit_status_ready=lambda: False)
        channel.recv_ready.return_value = False
        return channel

    def test_ping_success_keeps_streaming(self):
        source = _source()
        source._IDLE_PING_SECONDS = 0.02
        source._channel = self._idle_channel()

        calls = {"n": 0}

        def fake_ping():
            calls["n"] += 1
            if calls["n"] >= 2:
                source._canceled = lambda: True
            return True

        source._connection = MagicMock(ping=fake_ping)
        source.receive(0.1)
        self.assertGreaterEqual(calls["n"], 2)

    def test_ping_failure_raises_connection_lost(self):
        source = _source()
        source._IDLE_PING_SECONDS = 0.02
        source._channel = self._idle_channel()
        source._connection = MagicMock(ping=lambda: False)
        with self.assertRaisesRegex(ConnectionError, "no response"):
            source.receive(0.1)


if __name__ == "__main__":
    unittest.main()
