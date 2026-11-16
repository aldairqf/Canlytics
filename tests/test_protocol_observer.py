from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from services.protocol_observer import IsoTpObserver, decode_obd, decode_uds
from services.error_diagnostics import ErrorFrameCounter, decode_can_error_classes
from services.can_data_parser import load_can_dataframe, parse_candump_error_record
from services.can_sources import parse_candump_error_line
from services.can_sources import ReplayCanSource


class IsoTpObserverTests(unittest.TestCase):
    def test_single_frame(self):
        observer = IsoTpObserver()
        message = observer.ingest(0x7E8, b"\x03\x22\xf1\x90", 0)[0]
        self.assertEqual((message.can_id, message.payload), (0x7E8, b"\x22\xf1\x90"))

    def test_multiframe_and_invalid_sequence(self):
        observer = IsoTpObserver()
        observer.ingest(0x7E8, b"\x10\x0a123456", 0)
        self.assertEqual(observer.ingest(0x7E8, b"\x21abcd", .1)[0].payload, b"123456abcd")
        observer.ingest(0x7E9, b"\x10\x0a123456", 0)
        self.assertEqual(observer.ingest(0x7E9, b"\x22abcd", .1), ())

    def test_timeout_and_decoders(self):
        observer = IsoTpObserver(.5)
        observer.ingest(0x7E8, b"\x10\x0a123456", 0)
        self.assertEqual(observer.expire(1), 1)
        self.assertEqual(decode_uds(b"\x7f\x22\x31")["nrc"], 0x31)
        self.assertEqual(decode_obd(b"\x41\x0c")["pid"], 0x0c)
        self.assertEqual(decode_obd(b"\x7f\x01\x11")["nrc"], 0x11)

    def test_flow_control_is_ignored_and_first_frame_can_expire(self):
        observer = IsoTpObserver(.2)
        self.assertEqual(observer.ingest(1, b"\x30\x00\x00", 0), ())
        observer.ingest(0x7E8, b"\x10\x0a123456", 0)
        self.assertEqual(observer.ingest(0x7E8, b"\x21abcd", .3), ())

    def test_invalid_single_frame_lengths_are_ignored(self):
        observer = IsoTpObserver()
        self.assertEqual(observer.ingest(0x7E8, b"\x00\x22\xf1", 0), ())
        self.assertEqual(observer.ingest(0x7E8, b"\x04\x22\xf1", 0.1), ())

    def test_only_diagnostic_ids_are_observed(self):
        observer = IsoTpObserver()
        for can_id in (0x123, 0x18FEF100, 0xCF00400):
            self.assertEqual(observer.ingest(can_id, b"\x03\x22\xf1\x90", 0), ())
        self.assertEqual(observer.ingest(0x18DAF110, b"\x03\x22\xf1\x90", 0)[0].payload,
                         b"\x22\xf1\x90")
        configured = IsoTpObserver(can_ids=(0x123,))
        self.assertEqual(configured.ingest(0x123, b"\x03\x22\xf1\x90", 0)[0].payload,
                         b"\x22\xf1\x90")

    def test_timeout_is_refreshed_by_each_consecutive_frame(self):
        observer = IsoTpObserver(1.0)
        self.assertEqual(observer.ingest(0x7E8, b"\x10\x64abcdef", 0), ())
        result = ()
        for index in range(14):
            result = observer.ingest(0x7E8, bytes((0x20 | ((index + 1) & 0x0F),)) + b"1234567",
                                     (index + 1) * 0.1)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0].payload), 100)

    def test_uds_positive_response_and_response_pending_classification(self):
        for request_sid in (0x10, 0x11, 0x19, 0x22, 0x27, 0x2E, 0x31, 0x3E):
            decoded = decode_uds(bytes((request_sid + 0x40, 0x00)))
            self.assertTrue(decoded["positive"])
            self.assertEqual(decoded["request_sid"], request_sid)
        pending = decode_uds(b"\x7f\x22\x78")
        self.assertEqual(pending["nrc"], 0x78)
        self.assertTrue(pending["response_pending"])

    def test_obd_decoder_rejects_non_mode_services(self):
        self.assertTrue(decode_obd(b"\x01\x0c")["valid"])
        self.assertTrue(decode_obd(b"\x41\x0c")["valid"])
        self.assertFalse(decode_obd(b"\x62\xf1\x90")["valid"])


class ErrorFrameTests(unittest.TestCase):
    def test_candump_flag_and_errorframe_are_diagnostics_only(self):
        self.assertEqual(parse_candump_error_record("(1.0) can0 20000004#01")["type"], "candump_error_flag")
        self.assertEqual(parse_candump_error_line("(1.0) can0 20000004#01").is_error, True)
        self.assertEqual(parse_candump_error_line("(1.1) can0 ERRORFRAME").error_type, "errorframe")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_text("(1.0) can0 123#01\n(1.1) can0 20000004#01\n(1.2) can0 ERRORFRAME\n", encoding="utf-8")
            errors = []
            dataframe = load_can_dataframe(path, on_error_frame=errors.append)
            self.assertEqual(dataframe.height, 1)
            self.assertEqual([error["type"] for error in errors], ["candump_error_flag", "errorframe"])

    def test_error_counter_separates_kinds_and_resets(self):
        counter = ErrorFrameCounter()
        counter.ingest([type("Frame", (), {"error_type": "bus"})(),
                        type("Frame", (), {"error_type": "kvaser_error"})()])
        counter.record("transport")
        self.assertEqual(counter.snapshot().counts, {"bus": 1, "kvaser_error": 1, "transport": 1})
        counter.reset()
        self.assertEqual(counter.snapshot().total, 0)

    def test_error_frame_total_does_not_double_count_decoded_classes(self):
        counter = ErrorFrameCounter()
        snapshot = counter.record("candump_error_flag", can_id=0x20000020)
        self.assertEqual(snapshot.total, 1)
        self.assertEqual(snapshot.counts, {"candump_error_flag": 1})
        self.assertEqual(snapshot.classes, {"ack": 1})

    def test_controller_error_payload_uses_linux_can_error_byte_offsets(self):
        lost_arbitration = decode_can_error_classes(0, bytes((0x01, 0, 0, 0, 0)))
        controller = decode_can_error_classes(0, bytes((0, 0x01, 0, 0, 0)))
        protocol_type = decode_can_error_classes(0, bytes((0, 0, 0x01, 0, 0)))
        protocol_location = decode_can_error_classes(0, bytes((0, 0, 0, 0x03, 0)))
        transceiver = decode_can_error_classes(0, bytes((0, 0, 0, 0, 0x03)))
        self.assertIn("lost_arbitration", lost_arbitration)
        self.assertIn("controller", controller)
        self.assertIn("protocol", protocol_type)
        self.assertIn("protocol", protocol_location)
        self.assertNotIn("transceiver", protocol_location)
        self.assertIn("transceiver", transceiver)

    def test_imported_error_rate_uses_log_timestamps(self):
        counter = ErrorFrameCounter()
        counter.record("candump_error_flag", timestamp=10.0)
        snapshot = counter.record("candump_error_flag", timestamp=12.0)
        self.assertEqual(snapshot.rate_per_minute, 60.0)

    def test_live_error_rate_uses_sliding_monotonic_window(self):
        counter = ErrorFrameCounter()
        with patch("services.error_diagnostics.monotonic", side_effect=(10.0, 80.0)):
            counter.record("bus")
            snapshot = counter.record("bus")
        self.assertEqual(snapshot.total, 2)
        self.assertEqual(snapshot.rate_per_minute, 1.0)

    def test_replay_yields_error_record_outside_dataframe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.log"
            path.write_text("(1.0) can0 123#01\n(1.5) can0 20000004#00\n(2.0) can0 123#02\n", encoding="utf-8")
            source = ReplayCanSource({"path": str(path), "speed": 1000000})
            source.open(canceled=lambda: False, status=lambda _s: None)
            first = source.receive(0)
            error = source.receive(0)
            last = source.receive(0)
        self.assertFalse(first.is_error)
        self.assertTrue(error.is_error)
        self.assertFalse(last.is_error)

    def test_replay_passes_error_callback_during_single_import_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.log"
            path.write_text("(1.0) can0 123#01\n(1.5) can0 20000004#01\n", encoding="utf-8")
            from services.can_data_parser import load_can_dataframe
            with patch("services.can_sources.load_can_dataframe", wraps=load_can_dataframe) as load:
                source = ReplayCanSource({"path": str(path), "speed": 1_000_000})
                source.open(canceled=lambda: False, status=lambda _s: None)
        self.assertEqual(load.call_count, 1)
        self.assertIsNotNone(load.call_args.kwargs.get("on_error_frame"))

    def test_odd_length_error_payload_does_not_break_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.log"
            path.write_text("(1.0) can0 20000004#A ERRORFRAME\n", encoding="utf-8")
            source = ReplayCanSource({"path": str(path), "speed": 1_000_000})
            source.open(canceled=lambda: False, status=lambda _s: None)
            frame = source.receive(0)
        self.assertTrue(frame.is_error)

    def test_kvaser_error_lines_are_removed_from_data_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.txt"
            path.write_text(
                "Kvaser Memorator Log\n"
                "0.0 1 123x R 1 01\n"
                "0.1 1 20000004x ERROR 8 00 04 00 00 00 00 00 00\n"
                "0.2 1 20000005x ErrorFrame 8 00 01 00 00 00 00 00 00\n",
                encoding="utf-8",
            )
            errors = []
            dataframe = load_can_dataframe(path, on_error_frame=errors.append)
        self.assertEqual(dataframe["ID"].to_list(), ["123"])
        self.assertEqual(len(errors), 2)
        self.assertEqual(errors[1]["DATA"], "0001000000000000")


if __name__ == "__main__":
    unittest.main()
