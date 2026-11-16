from __future__ import annotations

import unittest

from services.j1939_transmit import (
    J1939AbortError,
    J1939TransmitSession,
)
from utils.j1939 import J1939


class J1939TransmitSessionTests(unittest.TestCase):
    def test_bam_uses_priority_seven_and_50ms_inter_packet_delay(self):
        session = J1939TransmitSession(0xFECA, bytes(range(15)), 0x80, 0xFF, now=0.0)
        first = session.start()
        self.assertEqual(J1939.decode_identifier(first.can_id).priority, 7)
        self.assertEqual(first.data[0], 0x20)
        self.assertEqual(session.on_send_result(True, now=0.0), [])
        self.assertIsNone(session.tick(now=0.049))
        self.assertEqual(session.tick(now=0.05)[0].data[0], 1)
        session.on_send_result(True, now=0.05)
        self.assertIsNone(session.tick(now=0.099))
        self.assertEqual(session.tick(now=0.10)[0].data[0], 2)

    def test_rts_partial_cts_and_retransmit_window(self):
        session = J1939TransmitSession(0xFECA, bytes(range(28)), 0x80, 0x0B, now=0.0)
        session.start()
        session.on_send_result(True, now=0.0)
        frames = session.receive(0x18EC800B, bytes((0x11, 2, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        self.assertEqual([frame.data[0] for frame in frames], [1])
        frames = session.on_send_result(True, now=0.11)
        self.assertEqual([frame.data[0] for frame in frames], [2])
        session.on_send_result(True, now=0.12)
        # A new CTS can request packet 2 again after it was already sent.
        frames = session.receive(0x18EC800B, bytes((0x11, 1, 2, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.15)
        self.assertEqual([frame.data[0] for frame in frames], [2])
        session.on_send_result(True, now=0.16)
        frames = session.receive(0x18EC800B, bytes((0x11, 2, 3, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.2)
        self.assertEqual([frame.data[0] for frame in frames], [3])
        frames = session.on_send_result(True, now=0.21)
        self.assertEqual([frame.data[0] for frame in frames], [4])

    def test_cts_hold_timeout_and_abort_reason(self):
        hold = J1939TransmitSession(0xFECA, bytes(range(20)), 0x80, 0x0B, now=0.0)
        hold.start()
        hold.on_send_result(True, now=0.0)
        hold.receive(0x18EC800B, bytes((0x11, 0, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        self.assertIsNone(hold.tick(now=1.0))
        timed_out = hold.tick(now=hold.timeouts.t3 + 0.2)
        self.assertEqual(timed_out[0].data[0], 0xFF)
        self.assertIsInstance(hold.error, TimeoutError)

        aborted = J1939TransmitSession(0xFECA, bytes(range(20)), 0x80, 0x0B, now=0.0)
        aborted.start()
        aborted.on_send_result(True, now=0.0)
        with self.assertRaises(J1939AbortError) as error:
            aborted.receive(0x18EC800B, bytes((0xFF, 3, 0xFF, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        self.assertEqual(error.exception.reason, 3)

    def test_t3_cts_and_eom_and_t4_hold_expire_and_eom_ack_completes(self):
        t1 = J1939TransmitSession(0xFECA, bytes(range(20)), 0x80, 0x0B, now=0.0)
        t1.start()
        t1.on_send_result(True, now=0.0)
        self.assertEqual(t1.tick(now=t1.timeouts.t3 + 0.01)[0].data[0], 0xFF)

        t2 = J1939TransmitSession(0xFECA, bytes(range(28)), 0x80, 0x0B, now=0.0)
        t2.start()
        t2.on_send_result(True, now=0.0)
        packet = t2.receive(0x18EC800B, bytes((0x11, 1, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)[0]
        self.assertEqual(packet.data[0], 1)
        t2.on_send_result(True, now=0.11)
        self.assertEqual(t2.state, "wait_cts")
        self.assertEqual(t2.tick(now=0.11 + t2.timeouts.t3 + 0.01)[0].data[0], 0xFF)

        t4 = J1939TransmitSession(0xFECA, bytes(range(7)), 0x80, 0x0B, now=0.0)
        t4.start()
        t4.on_send_result(True, now=0.0)
        packet = t4.receive(0x18EC800B, bytes((0x11, 1, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)[0]
        self.assertEqual(packet.data[0], 1)
        t4.on_send_result(True, now=0.11)
        self.assertEqual(t4.state, "wait_eom")
        self.assertEqual(t4.tick(now=0.11 + t4.timeouts.t3 + 0.01)[0].data[0], 0xFF)

        eom = J1939TransmitSession(0xFECA, bytes(range(7)), 0x80, 0x0B, now=0.0)
        eom.start()
        eom.on_send_result(True, now=0.0)
        eom.receive(0x18EC800B, bytes((0x11, 1, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        eom.on_send_result(True, now=0.11)
        self.assertEqual(eom.receive(0x18EC800B, bytes((0x13, 7, 0, 1, 0xFF, 0xCA, 0xFE, 0)), now=0.12), [])
        self.assertEqual(eom.state, "complete")

    def test_sender_uses_j1939_sender_timeout_mapping(self):
        session = J1939TransmitSession(0xFECA, bytes(range(7)), 0x80, 0x0B, now=0.0)
        session.start()
        session.on_send_result(True, now=0.0)
        self.assertAlmostEqual(session._deadline, 1.25)
        session.receive(0x18EC800B, bytes((0x11, 1, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        session.on_send_result(True, now=0.11)
        self.assertAlmostEqual(session._deadline, 1.36)

        hold = J1939TransmitSession(0xFECA, bytes(range(7)), 0x80, 0x0B, now=0.0)
        hold.start()
        hold.on_send_result(True, now=0.0)
        hold.receive(0x18EC800B, bytes((0x11, 0, 0, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        self.assertAlmostEqual(hold._deadline, 1.15)

    def test_timeout_emits_one_abort_and_preserves_original_error(self):
        session = J1939TransmitSession(0xFECA, bytes(range(20)), 0x80, 0x0B, now=0.0)
        session.start()
        session.on_send_result(True, now=0.0)
        abort = session.tick(now=2.0)
        original_error = session.error
        self.assertEqual(len(abort), 1)
        self.assertIsNone(session.tick(now=2.1))
        self.assertIs(session.error, original_error)
        self.assertIsNone(session._deadline)

    def test_bam_clears_due_time_while_waiting_for_send_result(self):
        session = J1939TransmitSession(0xFECA, bytes(range(15)), 0x80, 0xFF, now=0.0)
        session.start()
        session.on_send_result(True, now=0.0)
        session.tick(now=0.05)
        self.assertIsNone(session._next_due)

    def test_control_frame_validity_uses_rts_request_timestamp(self):
        session = J1939TransmitSession(0xFECA, bytes(range(20)), 0x80, 0x0B, now=0.0)
        session.start()
        stale_abort = bytes((0xFF, 1, 0xFF, 0xFF, 0xFF, 0xCA, 0xFE, 0))
        self.assertEqual(session.receive(0x18EC800B, stale_abort, now=-0.02), [])
        self.assertEqual(session.state, "send_announce")
        session.on_send_result(True, now=1.0)
        with self.assertRaises(J1939AbortError):
            session.receive(0x18EC800B, stale_abort, now=0.8)

    def test_abort_mid_window_fails_immediately_and_cts_mid_window_aborts(self):
        session = J1939TransmitSession(0xFECA, bytes(range(70)), 0x80, 0x0B, now=0.0)
        session.start()
        session.on_send_result(True, now=0.0)
        session.receive(0x18EC800B, bytes((0x11, 10, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        with self.assertRaises(J1939AbortError) as error:
            session.receive(0x18EC800B, bytes((0xFF, 1, 0xFF, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.11)
        self.assertEqual(error.exception.reason, 1)
        self.assertEqual(session.state, "failed")

        session = J1939TransmitSession(0xFECA, bytes(range(70)), 0x80, 0x0B, now=0.0)
        session.start()
        session.on_send_result(True, now=0.0)
        session.receive(0x18EC800B, bytes((0x11, 10, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        abort = session.receive(0x18EC800B, bytes((0x11, 1, 2, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.11)
        self.assertEqual(abort[0].data[:2], bytes((0xFF, 4)))
        self.assertEqual(session.state, "send_abort")

    def test_session_waits_for_abort_send_result_when_dt_is_still_pending(self):
        session = J1939TransmitSession(0xFECA, bytes(range(70)), 0x80, 0x0B, now=0.0)
        session.start()
        session.on_send_result(True, now=0.0, frame_kind="announce")
        session.receive(0x18EC800B, bytes((0x11, 10, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.1)
        abort = session.receive(0x18EC800B, bytes((0x11, 1, 2, 0xFF, 0xFF, 0xCA, 0xFE, 0)), now=0.11)
        self.assertEqual(abort[0].data[:2], bytes((0xFF, 4)))
        session.on_send_result(True, now=0.12, frame_kind="dt")
        self.assertEqual(session.state, "send_abort")
        session.on_send_result(True, now=0.13, frame_kind="abort")
        self.assertEqual(session.state, "failed")

    def test_local_failure_returns_connection_abort(self):
        session = J1939TransmitSession(0xFECA, bytes(range(20)), 0x80, 0x0B, now=0.0)
        session.start()
        abort = session.on_send_result(False, now=0.1, error="bus failed")
        self.assertEqual(abort[0].data[0], 0xFF)
        self.assertEqual(abort[0].data[1], 2)
        self.assertEqual(J1939.decode_identifier(abort[0].can_id).priority, 7)
        session.on_send_result(True, now=0.2)
        self.assertEqual(session.state, "failed")
        self.assertIsInstance(session.error, RuntimeError)


if __name__ == "__main__":
    unittest.main()
