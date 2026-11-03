from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from services.can_send import ResolvedFrame
from services.can_source import SourceFrame
from services.can_sources import KvaserCanSource, ReplayCanSource, SshCanSource
from services.can_stream import CanStreamRunner


class CanSourceImportTests(unittest.TestCase):
    def test_service_imports_do_not_require_qt_or_hardware_modules(self) -> None:
        script = (
            "import sys; import services.can_source, services.can_sources, services.can_stream; "
            "assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules); "
            "assert 'can' not in sys.modules; assert 'paramiko' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class KvaserCanSourceTests(unittest.TestCase):
    def test_probe_skips_silent_bitrate_then_keeps_first_valid_bus(self) -> None:
        clock = [0.0]

        class FakeBus:
            def __init__(self, bitrate: int):
                self.bitrate = bitrate
                self.closed = False

            def recv(self, timeout: float):
                if self.bitrate == 250000:
                    return type("Message", (), {
                        "arbitration_id": 0x321, "data": b"\x01", "timestamp": 10.0,
                        "channel": "0", "is_error_frame": False,
                    })()
                clock[0] += timeout
                return None

            def shutdown(self):
                self.closed = True

        buses: list[FakeBus] = []

        class FakeCan:
            @staticmethod
            def Bus(**kwargs):
                bus = FakeBus(kwargs["bitrate"])
                buses.append(bus)
                return bus

        source = KvaserCanSource(
            {
                "interface": "kvaser", "channel": "0", "try_all_bitrates": True,
                "bitrate_candidates": [125000, 250000],
            },
            can_module=FakeCan,
            platform="test",
            monotonic=lambda: clock[0],
        )
        statuses: list[str] = []
        source.open(canceled=lambda: False, status=statuses.append)
        frame = source.receive(0.1)

        self.assertEqual(source.bitrate, 250000)
        self.assertTrue(buses[0].closed)
        self.assertIs(buses[1], source._bus)
        self.assertEqual(frame, SourceFrame(0x321, b"\x01", 10.0, "0"))
        self.assertEqual(statuses, ["Probing 125000 bps (1/2)...", "Probing 250000 bps (2/2)..."])
        source.close()

    def test_send_uses_python_can_message_and_active_bus(self) -> None:
        sent: list[object] = []

        class FakeBus:
            def send(self, message):
                sent.append(message)

            def shutdown(self):
                pass

        class FakeCan:
            Message = dict

        source = KvaserCanSource({"interface": "kvaser", "channel": "0"}, can_module=FakeCan)
        source._bus = FakeBus()
        source.send(ResolvedFrame("entry", 0x321, b"\x01\x02", True))

        self.assertEqual(sent, [{
            "arbitration_id": 0x321, "data": b"\x01\x02", "is_extended_id": True, "dlc": 2,
        }])


class ReplayCanSourceTests(unittest.TestCase):
    def test_replay_returns_elapsed_device_time_and_honors_speed(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "logs" / "candump-sample.log"
        ticks = [0.0]

        def sleep(seconds: float) -> None:
            ticks[0] += seconds

        source = ReplayCanSource(
            {"path": str(fixture), "speed": 1000.0},
            monotonic=lambda: ticks[0],
            sleep=sleep,
        )
        statuses: list[str] = []
        source.open(canceled=lambda: False, status=statuses.append)
        first = source.receive(0.1)
        second = source.receive(0.1)

        self.assertIsNotNone(first)
        self.assertEqual(first.timestamp, 0.0)
        self.assertEqual(second.timestamp, 1779067270.673165 - 1779067270.672182)
        self.assertGreaterEqual(ticks[0], second.timestamp / 1000.0)
        self.assertEqual(statuses, [f"Replay: {fixture.name}"])
        source.close()

    def test_close_during_cancel_check_keeps_the_active_iterator(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "logs" / "candump-sample.log"
        source = ReplayCanSource({"path": str(fixture), "speed": 1000.0})
        source.open(canceled=lambda: False, status=lambda _status: None)

        close_calls: list[bool] = []

        def cancel_during_receive_check() -> bool:
            close_calls.append(True)
            source.close()
            return False

        source._canceled = cancel_during_receive_check

        frame = source.receive(0.1)

        self.assertIsNotNone(frame)
        self.assertEqual(close_calls, [True])
        self.assertEqual(frame.can_id, 0xCFE6CEE)


class CanStreamRunnerTests(unittest.TestCase):
    def test_device_timestamps_normalize_add_offset_and_flush_final_chunk(self) -> None:
        class FakeSource:
            bitrate = 500000
            finished = False

            def __init__(self):
                self.frames = [
                    SourceFrame(0x321, b"\x01\x02", 10.0, "can0", length=1),
                    SourceFrame(0x321, b"\x02", 12.5, "can0"),
                    SourceFrame(0x321, b"\x03", 13.0, "can0", is_error=True),
                ]

            def open(self, *, canceled, status):
                status("Connected")

            def receive(self, timeout):
                if self.frames:
                    return self.frames.pop(0)
                self.finished = True
                return None

            def send(self, frame):
                raise AssertionError("send is not used in this test")

            def close(self):
                self.finished = True

        source = FakeSource()
        chunks = []
        statuses: list[str] = []
        bitrate: list[int] = []
        runner = CanStreamRunner(
            source,
            {"mode": "kvaser", "ts_source": "device", "normalize": True, "ts_offset": 4.0},
            canceled=lambda: source.finished,
            status=statuses.append,
            on_chunk=chunks.append,
            on_bitrate=bitrate.append,
            wall_time=lambda: 99.0,
            monotonic=lambda: 100.0,
        )
        runner.run()

        self.assertEqual(bitrate, [500000])
        self.assertEqual(statuses, ["Connected", "Stopped"])
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["TS"].to_list(), [4.0, 6.5])
        self.assertEqual(chunks[0]["DATA"].to_list(), ["0102", "02"])
        self.assertEqual(chunks[0]["LEN"].to_list(), [1, 1])


class SshCanSourceTests(unittest.TestCase):
    def test_open_and_parse_candump_line_without_eager_paramiko_import(self) -> None:
        class FakeChannel:
            closed = False

            def __init__(self):
                self._data = [b"(1.250000) can0 321#0102\n"]

            def get_pty(self):
                pass

            def exec_command(self, command: str):
                self.command = command

            def settimeout(self, value: float):
                pass

            def recv_ready(self):
                return bool(self._data)

            def recv(self, size: int):
                return self._data.pop(0)

            def exit_status_ready(self):
                return False

            def close(self):
                self.closed = True

        class FakeConnection:
            def __init__(self, *_args):
                self.channel = FakeChannel()

            def open(self, *, cancel_check):
                self.cancel_check = cancel_check

            def exec_stream(self, command):
                self.channel.exec_command(command)
                return self.channel

            def ping(self):
                return True

            def cancel(self):
                pass

        fake_connection = FakeConnection()
        with patch("services.remote_connection.RemoteConnection", return_value=fake_connection):
            source = SshCanSource({
                "host": "device", "username": "user", "iface": "can0",
                "ts_source": "device",
            })
            statuses: list[str] = []
            source.open(canceled=lambda: False, status=statuses.append)
            frame = source.receive(0.1)

        self.assertEqual(frame, SourceFrame(0x321, b"\x01\x02", 1.25, "can0", length=2))
        self.assertEqual(fake_connection.channel.command, "candump -ta can0")
        self.assertEqual(statuses, ["Connecting via SSH...", "Streaming: candump -ta can0"])
        source.close()


if __name__ == "__main__":
    unittest.main()
