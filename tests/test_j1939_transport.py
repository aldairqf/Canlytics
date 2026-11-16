from __future__ import annotations

import unittest

import polars as pl

from services.j1939_transport import J1939CommandedReceiver, assemble_transport_messages
from utils.j1939 import J1939


def _df(rows: list[tuple[float, str, str]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=[("TS", pl.Float64), ("ID", pl.String), ("DATA", pl.String)], orient="row")


class J1939TransportTests(unittest.TestCase):
    def test_commanded_receiver_uses_rts_packet_limit_and_rearms_on_each_dt(self):
        receiver = J1939CommandedReceiver(0xFECA, 0x80, 0x0A, window_size=16)
        rts = bytes((0x10, 140, 0, 20, 4, 0xCA, 0xFE, 0))
        cm_id = J1939.pgn_to_frame_id(0xEC00 | 0x80, priority=7, source_address=0x0A)
        control, _ = receiver.receive(0.0, cm_id, rts)
        self.assertEqual(control[1][1:3], bytes((4, 1)))
        self.assertAlmostEqual(receiver.deadline, 1.25)
        dt_id = J1939.pgn_to_frame_id(0xEB00 | 0x80, priority=7, source_address=0x0A)
        for sequence in range(1, 5):
            control, _ = receiver.receive(sequence * 0.3, dt_id, bytes((sequence,)) + bytes(7))
            timeout = 1.25 if sequence == 4 else 0.75
            self.assertAlmostEqual(receiver.deadline, sequence * 0.3 + timeout)
        self.assertEqual(control[1][1:3], bytes((4, 5)))

    def test_commanded_receiver_cts_count_respects_own_window_and_unlimited_peer(self):
        receiver = J1939CommandedReceiver(0xFECA, 0x80, 0x0A, window_size=3)
        cm_id = J1939.pgn_to_frame_id(0xEC00 | 0x80, priority=7, source_address=0x0A)
        control, _ = receiver.receive(0.0, cm_id, bytes((0x10, 140, 0, 20, 0xFF, 0xCA, 0xFE, 0)))
        self.assertEqual(control[1][1:3], bytes((3, 1)))
        dt_id = J1939.pgn_to_frame_id(0xEB00 | 0x80, priority=7, source_address=0x0A)
        control = None
        for sequence in range(1, 4):
            control, _ = receiver.receive(sequence * 0.1, dt_id, bytes((sequence,)) + bytes(7))
        self.assertEqual(control[1][1:3], bytes((3, 4)))

    def test_commanded_receiver_rejects_zero_rts_packet_limit_with_abort(self):
        receiver = J1939CommandedReceiver(0xFECA, 0x80, 0x0A)
        cm_id = J1939.pgn_to_frame_id(0xEC00 | 0x80, priority=7, source_address=0x0A)
        control, _ = receiver.receive(0.0, cm_id, bytes((0x10, 20, 0, 3, 0, 0xCA, 0xFE, 0)))
        self.assertEqual(control[1][:2], bytes((0xFF, 2)))
        self.assertFalse(receiver.active)

    def test_rts_cts_with_zero_destination_and_unlimited_cts_packets(self):
        rows = [
            (0.0, "1CEC000A", "10090002FFCAFE00"),
            (0.1, "1CEC0A00", "110201FFFFCAFE00"),
            (0.2, "1CEB000A", "0100112233445566"),
            (0.3, "1CEB000A", "02778899FFFFFFFF"),
        ]
        messages = assemble_transport_messages(_df(rows), 0xFECA)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].destination_address, 0)
        self.assertEqual(messages[0].data, bytes.fromhex("001122334455667788"))

    def test_directed_dt_does_not_contaminate_bam_for_same_source(self):
        rows = [
            (0.0, "18ECFF0A", "20090002FFCAFE00"),
            (0.1, "18EBFF0A", "0111223344556677"),
            (0.2, "1CEB000A", "02AABBCCDDEEFF00"),
            (0.3, "18EBFF0A", "028899AABBCCDDEE"),
        ]
        messages = assemble_transport_messages(_df(rows), 0xFECA)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].data, bytes.fromhex("112233445566778899"))

    def test_non_transport_progress_is_throttled(self):
        count = 10_000
        dataframe = _df([(i / 10, "18FEE30A", "0000000000000000") for i in range(count)])
        progress = []
        assemble_transport_messages(dataframe, on_progress=lambda done, total: progress.append((done, total)))
        self.assertLessEqual(len(progress), count // 40)
        self.assertEqual(progress[-1], (count, count))

    def test_other_pgn_connection_management_replaces_incomplete_bam(self):
        rows = [
            (0.0, "18ECFF0A", "20090002FFCAFE00"),
            (0.1, "18EBFF0A", "0111223344556677"),
            (0.2, "18ECFF0A", "20090002FF00F000"),
            (0.3, "18EBFF0A", "028899AABBCCDDEE"),
        ]
        self.assertEqual(assemble_transport_messages(_df(rows), 0xFECA), [])

    def test_reassembles_rts_cts_over_multiple_windows(self):
        dataframe = _df([
            (0.0, "0CEC0B0A", "1010000302CAFE00"),
            (0.1, "18EC0A0B", "110201FFFFCAFE00"),
            (0.2, "18EB0B0A", "0111223344556677"),
            (0.3, "18EB0B0A", "028899AABBCCDDEE"),
            (0.4, "18EC0A0B", "110103FFFFCAFE00"),
            (0.5, "18EB0B0A", "03FFEEDDCCBBAA99"),
            (0.6, "18EC0A0B", "13100003FFCAFE00"),
        ])
        messages = assemble_transport_messages(dataframe, 0xFECA)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].protocol, "CMDT")
        self.assertEqual(messages[0].source_address, 0x0A)
        self.assertEqual(messages[0].destination_address, 0x0B)
        self.assertEqual(messages[0].data, bytes.fromhex("112233445566778899AABBCCDDEEFFEE"))
        self.assertAlmostEqual(messages[0].timestamp, 0.5)

    def test_reassembles_interleaved_sessions_by_source_and_destination(self):
        dataframe = _df([
            (0.0, "18ECFF0A", "20090002FFCAFE00"),
            (0.1, "18ECFF0B", "20090002FFCAFE00"),
            (0.2, "18EBFF0A", "0111223344556677"),
            (0.3, "18EBFF0B", "01AABBCCDDEEFF00"),
            (0.4, "18EBFF0A", "028899AABBCCDDEE"),
            (0.5, "18EBFF0B", "0211223344556677"),
        ])
        messages = assemble_transport_messages(dataframe, 0xFECA)
        self.assertEqual({item.source_address for item in messages}, {0x0A, 0x0B})
        self.assertEqual(len(messages), 2)

    def test_rejects_bad_packet_counts_oversize_and_incomplete_sessions(self):
        dataframe = _df([
            (0.0, "18ECFF0A", "2009000100CAFE00"),  # 9 bytes needs 2 packets
            (0.1, "18ECFF0B", "20FF0700FFCAFE00"),  # exceeds the 1785-byte limit
            (0.2, "18ECFF0C", "20090002FFCAFE00"),
            (0.3, "18EBFF0C", "0101020304050607"),
        ])
        self.assertEqual(assemble_transport_messages(dataframe), [])

    def test_commanded_transfer_abort_discards_session(self):
        dataframe = _df([
            (0.0, "0CEC0B0A", "1009000202CAFE00"),
            (0.1, "18EC0A0B", "110201FFFFCAFE00"),
            (0.2, "18EB0B0A", "0111223344556677"),
            (0.3, "18EC0A0B", "FF000000FFCAFE00"),
            (0.4, "18EC0B0A", "110201FFFFCAFE00"),
            (0.5, "18EB0B0A", "028899AABBCCDDEE"),
        ])
        self.assertEqual(assemble_transport_messages(dataframe), [])

    def test_times_out_stale_session_and_reports_progress(self):
        dataframe = _df([
            (0.0, "18ECFF0A", "20090002FFCAFE00"),
            (6.0, "18EBFF0A", "0111223344556677"),
            (6.1, "18EBFF0A", "028899AABBCCDDEE"),
        ])
        progress = []
        self.assertEqual(
            assemble_transport_messages(dataframe, on_progress=lambda done, total: progress.append((done, total))),
            [],
        )
        self.assertEqual(progress[-1], (3, 3))

    def test_accepts_exact_payload_limit_and_rejects_out_of_window_packets(self):
        rows = [(0.0, "18ECFF0A", "20F906FFFFCAFE00")]
        rows.extend(
            (index / 10, "18EBFF0A", f"{index:02X}" + "11223344556677")
            for index in range(1, 256)
        )
        messages = assemble_transport_messages(_df(rows))
        self.assertEqual(len(messages), 1)
        self.assertEqual(len(messages[0].data), 1785)

        cmdt = _df([
            (0.0, "0CEC0B0A", "1009000202CAFE00"),
            (0.1, "18EC0A0B", "110201FFFFCAFE00"),
            (0.2, "18EB0B0A", "028899AABBCCDDEE"),
            (0.3, "18EB0B0A", "0111223344556677"),
            (0.4, "18EC0A0B", "110102FFFFCAFE00"),
            (0.5, "18EB0B0A", "0211223344556677"),
        ])
        self.assertEqual(assemble_transport_messages(cmdt), [])

    def test_rejects_invalid_rts_sequence_and_bam_session_abort(self):
        dataframe = _df([
            (0.0, "18ECFF0A", "20090002FFCAFE00"),
            (0.1, "18EBFF0A", "0301020304050607"),
            (0.2, "18ECFF0A", "FF000000FFCAFE00"),
            (0.3, "0CEC0B0B", "1009000202CAFE00"),
            (0.4, "18EC0B0A", "110201FFFFCAFE00"),
            (0.5, "18EB0A0B", "0001020304050607"),
            (0.6, "18EB0A0B", "0111223344556677"),
            (0.7, "18EB0A0B", "028899AABBCCDDEE"),
        ])
        self.assertEqual(assemble_transport_messages(dataframe), [])

    def test_message_callback_streams_results_without_retaining_them(self):
        dataframe = _df([
            (0.0, "18ECFF0A", "20090002FFCAFE00"),
            (0.1, "18EBFF0A", "0111223344556677"),
            (0.2, "18EBFF0A", "028899AABBCCDDEE"),
        ])
        received = []
        results = assemble_transport_messages(dataframe, on_message=received.append)
        self.assertEqual(results, [])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].pgn, 0xFECA)


if __name__ == "__main__":
    unittest.main()
