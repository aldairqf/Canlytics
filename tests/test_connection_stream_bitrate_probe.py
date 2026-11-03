"""Characterization tests for the service-owned Kvaser bitrate probe."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.can_sources import KvaserCanSource, SourceCanceled


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


def _source(can_module, candidates=(250000, 500000)) -> KvaserCanSource:
    source = KvaserCanSource(
        {
            "interface": "kvaser", "channel": "0", "try_all_bitrates": True,
            "bitrate_candidates": list(candidates),
        },
        can_module=can_module,
        platform="test",
    )
    source._BITRATE_PROBE_SECONDS = 0.05
    return source


class ProbeBitratesTests(unittest.TestCase):
    def test_first_candidate_with_traffic_wins(self):
        bus = _FakeBus([_FakeMsg()])
        can_module = MagicMock(Bus=MagicMock(return_value=bus))
        source = _source(can_module)

        source.open(canceled=lambda: False, status=lambda _status: None)

        self.assertEqual(source.bitrate, 250000)
        self.assertIs(source._bus, bus)
        bus.shutdown.assert_not_called()
        source.close()

    def test_skips_silent_candidate_and_keeps_next(self):
        silent_bus = _FakeBus([])  # never yields a message -> times out
        working_bus = _FakeBus([_FakeMsg()])
        can_module = MagicMock(Bus=MagicMock(side_effect=[silent_bus, working_bus]))
        source = _source(can_module)

        source.open(canceled=lambda: False, status=lambda _status: None)

        self.assertEqual(source.bitrate, 500000)
        self.assertIs(source._bus, working_bus)
        silent_bus.shutdown.assert_called_once()
        source.close()

    def test_error_frames_do_not_count_as_traffic(self):
        bus = _FakeBus([_FakeMsg(is_error_frame=True)])
        can_module = MagicMock(Bus=MagicMock(return_value=bus))
        source = _source(can_module, candidates=(250000,))

        with self.assertRaises(ConnectionError):
            source.open(canceled=lambda: False, status=lambda _status: None)

    def test_bus_construction_failure_skips_to_next_candidate(self):
        working_bus = _FakeBus([_FakeMsg()])
        can_module = MagicMock(Bus=MagicMock(side_effect=[RuntimeError("nope"), working_bus]))
        source = _source(can_module)

        source.open(canceled=lambda: False, status=lambda _status: None)

        self.assertEqual(source.bitrate, 500000)
        source.close()

    def test_no_candidate_works_raises(self):
        can_module = MagicMock(Bus=MagicMock(return_value=_FakeBus([])))
        source = _source(can_module)

        with self.assertRaises(ConnectionError):
            source.open(canceled=lambda: False, status=lambda _status: None)

    def test_stop_flag_aborts_early_without_raising(self):
        can_module = MagicMock(Bus=MagicMock(return_value=_FakeBus([])))
        source = _source(can_module)

        with self.assertRaises(SourceCanceled):
            source.open(canceled=lambda: True, status=lambda _status: None)
        can_module.Bus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
