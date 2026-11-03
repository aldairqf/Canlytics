from __future__ import annotations

import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from services.ssh_time_poll import SshTimePoller
from viewmodels.ssh_time_poll_viewmodel import SshTimePollViewModel

_app: QCoreApplication | None = None


def setUpModule():
    global _app
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)


class SshTimePollerTests(unittest.TestCase):
    def test_import_does_not_require_qt_or_hardware_modules(self) -> None:
        script = (
            "import sys; import services.ssh_time_poll; "
            "assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules); "
            "assert 'paramiko' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_parses_remote_candump_timestamps_and_closes_connection(self) -> None:
        class FakeChannel:
            def __init__(self):
                self.pending = [b"(1.250000) can0 321#0102\n"]

            def recv_ready(self):
                return bool(self.pending)

            def recv(self, size):
                return self.pending.pop(0)

        class FakeConnection:
            def __init__(self, *_args):
                self.channel = FakeChannel()
                self.closed = False

            def open(self, *, cancel_check):
                self.cancel_check = cancel_check

            def exec_stream(self, command):
                self.command = command
                return self.channel

            def cancel(self):
                pass

            def close(self):
                self.closed = True

        connection = FakeConnection()
        poller = SshTimePoller("device", object(), "can0")
        timestamps: list[float] = []

        def on_timestamp(timestamp: float) -> None:
            timestamps.append(timestamp)
            poller.stop()

        with patch("services.remote_connection.RemoteConnection", return_value=connection):
            poller.run(on_timestamp)

        self.assertEqual(timestamps, [1.25])
        self.assertEqual(connection.command, "candump -ta can0")
        self.assertTrue(connection.closed)


class SshTimePollViewModelTests(unittest.TestCase):
    def test_immediate_poll_completion_clears_worker_references(self) -> None:
        class ImmediatePoller:
            def __init__(self, *_args):
                pass

            def run(self, emit_timestamp):
                return None

            def stop(self):
                return None

        vm = SshTimePollViewModel()
        with patch("viewmodels.ssh_time_poll_viewmodel.SshTimePoller", ImmediatePoller):
            vm.start("device", "user", None, None, "can0")
            deadline = time.monotonic() + 2.0
            while vm._thread is not None and time.monotonic() < deadline:
                _app.processEvents()
                time.sleep(0.001)
            _app.processEvents()

        self.assertIsNone(vm._thread)
        self.assertIsNone(vm._worker)
        vm.deleteLater()
        _app.processEvents()

    def test_finished_signal_from_old_poll_does_not_clear_new_worker(self) -> None:
        class Poller:
            instances = 0

            def __init__(self, *_args):
                type(self).instances += 1
                self.index = type(self).instances
                self.stopped = False

            def run(self, emit_timestamp):
                while self.index == 2 and not self.stopped:
                    time.sleep(0.001)

            def stop(self):
                self.stopped = True

        vm = SshTimePollViewModel()
        with patch("viewmodels.ssh_time_poll_viewmodel.SshTimePoller", Poller):
            vm.start("device", "user", None, None, "can0")
            vm.start("device", "user", None, None, "can0")
            current_thread = vm._thread
            _app.processEvents()
            self.assertIs(vm._thread, current_thread)
            vm.stop()

        self.assertIsNone(vm._thread)
        self.assertIsNone(vm._worker)
        vm.deleteLater()
        _app.processEvents()


if __name__ == "__main__":
    unittest.main()
