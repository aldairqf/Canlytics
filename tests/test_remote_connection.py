"""Characterization tests for RemoteConnection.is_alive()/ping()."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.remote_connection import RemoteConnection, SshAuth


def _conn() -> RemoteConnection:
    return RemoteConnection("host", SshAuth(username="u"))


class IsAliveTests(unittest.TestCase):
    def test_no_client_is_not_alive(self):
        self.assertFalse(_conn().is_alive())

    def test_no_transport_is_not_alive(self):
        conn = _conn()
        conn.client = MagicMock(get_transport=lambda: None)
        self.assertFalse(conn.is_alive())

    def test_inactive_transport_is_not_alive(self):
        conn = _conn()
        transport = MagicMock(is_active=lambda: False)
        conn.client = MagicMock(get_transport=lambda: transport)
        self.assertFalse(conn.is_alive())

    def test_active_transport_is_alive(self):
        conn = _conn()
        transport = MagicMock(is_active=lambda: True)
        conn.client = MagicMock(get_transport=lambda: transport)
        self.assertTrue(conn.is_alive())


class PingTests(unittest.TestCase):
    def test_not_alive_skips_send_and_returns_false(self):
        conn = _conn()
        self.assertFalse(conn.ping())

    def test_send_ignore_success_returns_true(self):
        conn = _conn()
        transport = MagicMock(is_active=lambda: True)
        conn.client = MagicMock(get_transport=lambda: transport)
        self.assertTrue(conn.ping())
        transport.send_ignore.assert_called_once()

    def test_send_ignore_raises_returns_false(self):
        conn = _conn()
        transport = MagicMock(is_active=lambda: True)
        transport.send_ignore.side_effect = OSError("broken pipe")
        conn.client = MagicMock(get_transport=lambda: transport)
        self.assertFalse(conn.ping())


if __name__ == "__main__":
    unittest.main()
