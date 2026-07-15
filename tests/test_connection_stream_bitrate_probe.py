"""Characterization tests for _ConnectionStreamWorker's Kvaser bitrate probing."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from viewmodels.connection_stream_viewmodel import _ConnectionStreamWorker

_app: QApplication | None = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)


class _FakeMsg:
    def __init__(self, is_error_frame=False):
        self.is_error_frame = is_error_frame


class _FakeBus:
    def __init__(self, recv_results):
        self._recv_results = list(recv_results)
        self.shutdown = MagicMock()

    def recv(self, timeout=None):
        if self._recv_results:
            return self._recv_results.pop(0)
        return None


def _worker() -> _ConnectionStreamWorker:
    worker = _ConnectionStreamWorker({"mode": "kvaser"})
    worker._BITRATE_PROBE_SECONDS = 0.05
    return worker


class ProbeBitratesTests(unittest.TestCase):
    def test_first_candidate_with_traffic_wins(self):
        worker = _worker()
        bus = _FakeBus([_FakeMsg()])
        can_module = MagicMock(Bus=MagicMock(return_value=bus))

        result = worker._probe_bitrates(can_module, "kvaser", "0", {}, [250000, 500000])

        self.assertEqual(result, 250000)
        self.assertIs(worker._bus, bus)
        bus.shutdown.assert_not_called()

    def test_skips_silent_candidate_and_keeps_next(self):
        worker = _worker()
        silent_bus = _FakeBus([])  # never yields a message -> times out
        working_bus = _FakeBus([_FakeMsg()])
        can_module = MagicMock(Bus=MagicMock(side_effect=[silent_bus, working_bus]))

        result = worker._probe_bitrates(can_module, "kvaser", "0", {}, [250000, 500000])

        self.assertEqual(result, 500000)
        self.assertIs(worker._bus, working_bus)
        silent_bus.shutdown.assert_called_once()

    def test_error_frames_do_not_count_as_traffic(self):
        worker = _worker()
        bus = _FakeBus([_FakeMsg(is_error_frame=True)])
        can_module = MagicMock(Bus=MagicMock(return_value=bus))

        with self.assertRaises(ConnectionError):
            worker._probe_bitrates(can_module, "kvaser", "0", {}, [250000])

    def test_bus_construction_failure_skips_to_next_candidate(self):
        worker = _worker()
        working_bus = _FakeBus([_FakeMsg()])
        can_module = MagicMock(Bus=MagicMock(side_effect=[RuntimeError("nope"), working_bus]))

        result = worker._probe_bitrates(can_module, "kvaser", "0", {}, [250000, 500000])

        self.assertEqual(result, 500000)

    def test_no_candidate_works_raises(self):
        worker = _worker()
        can_module = MagicMock(Bus=MagicMock(return_value=_FakeBus([])))

        with self.assertRaises(ConnectionError):
            worker._probe_bitrates(can_module, "kvaser", "0", {}, [250000, 500000])

    def test_stop_flag_aborts_early_without_raising(self):
        worker = _worker()
        worker._stop = True
        can_module = MagicMock(Bus=MagicMock(return_value=_FakeBus([])))

        result = worker._probe_bitrates(can_module, "kvaser", "0", {}, [250000, 500000])

        self.assertIsNone(result)
        can_module.Bus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
