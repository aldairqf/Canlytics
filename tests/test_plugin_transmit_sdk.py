from __future__ import annotations

import unittest
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, QCoreApplication, QThread, Signal
import polars as pl

from canlytics_sdk import PluginAPI, SDK_API_VERSION
from services.j1939_transmit import build_transport_frames
from viewmodels.can_send_viewmodel import CanSendViewModel
from viewmodels.plugin_viewmodel import _PluginContext


class _Connection(QObject):
    chunk_ready = Signal(object)
    running_changed = Signal(bool)
    send_succeeded = Signal(str)
    send_failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.is_replay = False
        self.fail_message = None
        self.requested = []

    def request_send(self, frame):
        self.requested.append(frame)
        if self.fail_message:
            self.send_failed.emit(frame.entry_id, self.fail_message)
        else:
            self.send_succeeded.emit(frame.entry_id)


class PluginTransmitSdkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_example_plugin_registers_and_uses_versioned_transmit_api(self):
        context = _PluginContext(SimpleNamespace(connection_vm=_Connection()))
        api = PluginAPI("transmit_example")
        calls = []
        context.send_frame = Mock(return_value="entry-1")

        def register(plugin_api, plugin_context):
            plugin_api.register_context_action("request", lambda _context: calls.append(
                plugin_context.request_pgn(0xFECA, source_address=0x80)
            ))

        register(api, context)
        api.context_actions["request"](None)
        self.assertEqual(SDK_API_VERSION, 2)
        self.assertEqual(calls, ["entry-1"])
        context.send_frame.assert_called_once_with(
            0x18EAFF80, b"\xCA\xFE\x00", extended=True
        )

    def test_send_pgn_uses_actual_can_send_result_and_logs_replay_failure(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        sent = context.send_pgn(0xFECA, b"abc", source_address=0x80)
        self.assertTrue(sent.done())
        self.assertTrue(can_send.tx_log()[-1].success)
        self.assertEqual(len(connection.requested), 1)

        connection.is_replay = True
        rejected = context.send_pgn(0xFECA, b"abc", source_address=0x80)
        with self.assertRaisesRegex(RuntimeError, "Replay"):
            rejected.result()
        self.assertFalse(can_send.tx_log()[-1].success)
        self.assertIn("Replay", can_send.tx_log()[-1].message)
        connection.is_replay = False
        connection.running = False
        disconnected = context.send_pgn(0xFECA, b"abc", source_address=0x80)
        with self.assertRaisesRegex(RuntimeError, "Not connected"):
            disconnected.result()
        self.assertIn("Not connected", can_send.tx_log()[-1].message)
        can_send.shutdown()

    def test_busy_gui_does_not_reject_cts_timestamped_after_rts_request(self):
        class DeferredSend(QObject):
            plugin_send_finished = Signal(str, bool, str)

            def __init__(self):
                super().__init__()
                self.sent = []

            def send_plugin_frame(self, can_id, data, *, extended=False, entry_id=None):
                self.sent.append((entry_id, can_id, bytes(data)))
                return entry_id

        connection = _Connection()
        can_send = DeferredSend()
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        future = context.send_pgn(0xFECA, bytes(20), source_address=0x80, destination_address=0x10)
        operation = next(iter(context._operations.values()))
        requested_at = operation.session._control_valid_after
        time.sleep(0.05)
        entry_id = can_send.sent[0][0]
        can_send.plugin_send_finished.emit(entry_id, True, "")
        cts = bytes((0x11, 3, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0))
        latest_ts = 10.05
        connection.chunk_ready.emit(pl.DataFrame({
            "TS": [10.005, latest_ts],
            "ID": ["18EC8010", "18FEE310"],
            "DATA": [cts.hex().upper(), "0000000000000000"],
        }))
        self.assertGreaterEqual(operation.session._control_valid_after, requested_at - 0.05)
        self.assertEqual(operation.session.state, "send_window")
        self.assertEqual(can_send.sent[-1][2][0], 1)
        future.cancel()

    def test_send_frame_from_worker_is_marshaled_to_can_send_thread(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        result = []
        done = threading.Event()

        def send_from_worker():
            result.append(context.send_frame(0x123, b"\x01", extended=False))
            done.set()

        worker = threading.Thread(target=send_from_worker)
        worker.start()
        deadline = time.monotonic() + 1.0
        while not done.is_set() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        worker.join(timeout=0.1)
        self.assertTrue(done.is_set())
        self.assertEqual(len(connection.requested), 1)
        self.assertEqual(can_send.tx_log()[-1].can_id, "123")
        can_send.shutdown()

    def test_wait_for_handles_absent_connection_and_malformed_chunks(self):
        context = _PluginContext(SimpleNamespace())
        future = context.wait_for(0xFECA, None, 1.0)
        with self.assertRaisesRegex(RuntimeError, "receive stream is unavailable"):
            future.result()
        context._record_transport_frames(pl.DataFrame({"ID": ["1"], "DATA": ["00"]}))
        self.assertFalse(context._chunk_listener_connected)

    def test_rts_cts_send_completes_only_after_can_send_and_eom_ack(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        future = context.send_pgn(0xFECA, bytes(range(20)), source_address=0x80,
                                  destination_address=0x0B)
        self.assertFalse(future.done())
        self.assertEqual(len(can_send.tx_log()), 1)

        def emit(control: bytes):
            context._record_transport_frames(pl.DataFrame({
                "TS": [1.0], "ID": ["18EC800B"], "DATA": [control.hex().upper()]
            }))

        emit(bytes((0x11, 2, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0)))
        self.assertEqual([frame.data[0] for frame in connection.requested[-2:]], [1, 2])
        emit(bytes((0x11, 1, 3, 0xFF, 0xFF, 0xCA, 0xFE, 0)))
        self.assertEqual(connection.requested[-1].data[0], 3)
        self.assertFalse(future.done())
        emit(bytes((0x13, 20, 0, 3, 0xFF, 0xCA, 0xFE, 0)))
        self.assertTrue(future.done())
        self.assertEqual(len(can_send.tx_log()), 4)
        self.assertTrue(all(record.success for record in can_send.tx_log()))
        can_send.shutdown()

    def test_old_transport_controls_are_not_retained_for_new_sessions(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        old_eom = pl.DataFrame({
            "TS": [1.0], "ID": ["18EC800B"], "DATA": ["13140003FFCAFE00"]
        })
        connection.chunk_ready.emit(old_eom)
        self.assertFalse(context._chunk_listener_connected)
        future = context.send_pgn(0xFECA, bytes(range(20)), source_address=0x80,
                                  destination_address=0x0B)
        self.assertFalse(future.done())
        self.assertEqual(len(can_send.tx_log()), 1)
        future.cancel()
        self.app.processEvents()
        self.assertEqual(context._operations, {})
        self.assertFalse(context._chunk_listener_connected)
        self.assertEqual(can_send.tx_log()[-1].data_hex[:4], "FF02")
        can_send.shutdown()

    def test_concurrent_cmdt_sends_are_serialized_by_sa_da_pair(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        first = context.send_pgn(0xFECA, bytes([0xAA]) * 20, source_address=0x80,
                                 destination_address=0x10)
        second = context.send_pgn(0xFECA, bytes([0xBB]) * 20, source_address=0x80,
                                  destination_address=0x10)
        self.assertEqual(len(connection.requested), 1)
        control = bytes((0x11, 3, 1, 0xFF, 0xFF, 0xCA, 0xFE, 0))
        connection.chunk_ready.emit(pl.DataFrame({
            "TS": [1.0], "ID": ["18EC8010"], "DATA": [control.hex().upper()]
        }))
        self.assertEqual([frame.data[0] for frame in connection.requested], [0x10, 1, 2, 3])
        eom = bytes((0x13, 20, 0, 3, 0xFF, 0xCA, 0xFE, 0))
        connection.chunk_ready.emit(pl.DataFrame({
            "TS": [2.0], "ID": ["18EC8010"], "DATA": [eom.hex().upper()]
        }))
        self.assertTrue(first.done())
        self.assertEqual(connection.requested[-1].data[0], 0x10)
        self.assertFalse(second.done())
        first.exception()
        second.cancel()
        can_send.shutdown()

    def test_invalid_queued_transport_does_not_block_the_next_session(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        invalid = context.send_pgn(0xFECA, bytes(2000), source_address=0x80,
                                   destination_address=0x10)
        queued = context.send_pgn(0xFECA, bytes(20), source_address=0x80,
                                  destination_address=0x10)
        self.assertTrue(invalid.done())
        self.assertIsInstance(invalid.exception(), ValueError)
        self.assertEqual(len(connection.requested), 1)
        self.assertFalse(queued.done())
        queued.cancel()
        can_send.shutdown()

    def test_concurrent_bam_sends_are_serialized_by_source(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        first = context.send_pgn(0xFECA, bytes([0xAA]) * 9, source_address=0x80)
        second = context.send_pgn(0xFEDA, bytes([0xBB]) * 9, source_address=0x80)
        self.assertEqual(len(connection.requested), 1)
        deadline = time.monotonic() + 0.35
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertTrue(first.done())
        self.assertTrue(second.done())
        self.assertEqual(len(connection.requested), 6)
        self.assertEqual(connection.requested[0].data[5], 0xCA)
        self.assertEqual(connection.requested[3].data[5], 0xDA)
        can_send.shutdown()

    def test_shutdown_rejects_new_operations_and_non_bytes_payload(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        context.shutdown()
        sent = context.send_pgn(0xFECA, b"abc", source_address=0x80)
        waited = context.wait_for(0xFECA, None, 1.0)
        self.assertTrue(sent.done())
        self.assertTrue(waited.done())
        self.assertEqual(context._operations, {})
        self.assertEqual(len(connection.requested), 0)
        invalid = context.send_pgn(0xFECA, 5, source_address=0x80)
        self.assertTrue(invalid.done())
        self.assertIsInstance(invalid.exception(), TypeError)
        can_send.shutdown()

    def test_wait_timeout_is_bounded_before_operation_registration(self):
        connection = _Connection()
        context = _PluginContext(SimpleNamespace(connection_vm=connection))
        with self.assertRaises(ValueError):
            context.wait_for(0xFECA, None, 3.0e6)
        self.assertEqual(context._operations, {})
        with patch("viewmodels.plugin_viewmodel.QTimer.start", side_effect=OverflowError("timer range")):
            future = context.wait_for(0xFECA, None, 2.0)
        self.assertTrue(future.done())
        self.assertIsInstance(future.exception(), OverflowError)
        self.assertEqual(context._operations, {})
        self.assertFalse(context._chunk_listener_connected)

    def test_fail_fast_done_callback_added_from_worker_is_queued_to_gui(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        can_send.send_plugin_frame = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("Not connected")
        )
        main_thread = threading.get_ident()
        result = []
        done = threading.Event()

        def caller():
            future = context.send_pgn(0xFECA, b"abc", source_address=0x80)
            future.add_done_callback(lambda _future: (result.append(threading.get_ident()), done.set()))

        worker = threading.Thread(target=caller)
        worker.start()
        deadline = time.monotonic() + 1.0
        while not done.is_set() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        worker.join(timeout=0.1)
        self.assertTrue(done.is_set())
        self.assertEqual(result, [main_thread])
        can_send.shutdown()

    def test_callback_is_not_run_outside_gui_when_application_is_unavailable(self):
        context = _PluginContext(SimpleNamespace(connection_vm=None))
        called = []
        with patch.object(QCoreApplication, "instance", return_value=None):
            future = context.wait_for(0xFECA, None, 1.0)
            future.add_done_callback(lambda _future: called.append(threading.get_ident()))
            context._dispatch_callback(lambda: called.append(threading.get_ident()))
        self.assertTrue(future.done())
        self.assertIsInstance(future.exception(), RuntimeError)
        self.assertEqual(called, [])

    def test_wait_for_answers_directed_cmdt_with_cts_and_eom_ack(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        future = context.wait_for(0xFECA, 0x10, 2.0, local_source_address=0x80)
        context.request_pgn(0xFECA, source_address=0x80)
        self.assertIsNotNone(next(op for op in context._operations.values() if op.kind == "wait").commanded_receiver)
        rts = bytes((0x10, 20, 0, 3, 0xFF, 0xCA, 0xFE, 0))
        connection.chunk_ready.emit(pl.DataFrame({
            "TS": [1.0], "ID": ["18EC8010"], "DATA": [rts.hex().upper()]
        }))
        self.assertEqual(connection.requested[-1].data[0], 0x11)
        self.assertEqual(connection.requested[-1].data[1:3], bytes((3, 1)))
        for sequence, payload in enumerate((b"abcdefg", b"hijklmn", b"opqrst"), start=1):
            time.sleep(0.3)
            dt = bytes((sequence,)) + payload.ljust(7, b"\xff")
            connection.chunk_ready.emit(pl.DataFrame({
                "TS": [1.0 + sequence / 10], "ID": ["18EB8010"], "DATA": [dt.hex().upper()]
            }))
            self.app.processEvents()
        self.assertTrue(future.done())
        self.assertEqual(future.result().data, b"abcdefghijklmnopqrst")
        self.assertEqual(connection.requested[-1].data[0], 0x13)
        can_send.shutdown()

    def test_active_cmdt_receiver_timeout_sends_abort_and_fails_wait(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        future = context.wait_for(0xFECA, 0x10, 5.0, local_source_address=0x80)
        rts = bytes((0x10, 20, 0, 3, 0xFF, 0xCA, 0xFE, 0))
        connection.chunk_ready.emit(pl.DataFrame({
            "TS": [1.0], "ID": ["18EC8010"], "DATA": [rts.hex().upper()]
        }))
        operation_id, operation = next(iter(context._operations.items()))
        self.assertTrue(operation.commanded_receiver.active)
        operation.commanded_receiver.deadline = time.monotonic() - 0.01
        context._receiver_timeout(operation_id)
        self.assertTrue(future.done())
        self.assertIsInstance(future.exception(), TimeoutError)
        self.assertEqual(connection.requested[-1].data[:2], bytes((0xFF, 3)))
        self.assertTrue(can_send.tx_log()[-1].success)
        can_send.shutdown()

    def test_bam_frames_are_timer_spaced_and_local_failure_sends_abort(self):
        connection = _Connection()
        can_send = CanSendViewModel(None, connection, None)
        context = _PluginContext(SimpleNamespace(connection_vm=connection, can_send_vm=can_send))
        future = context.send_pgn(0xFECA, bytes(range(15)), source_address=0x80)
        self.assertEqual(len(connection.requested), 1)
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertTrue(future.done())
        self.assertEqual(len(connection.requested), 4)
        self.assertTrue(all(record.success for record in can_send.tx_log()))
        tx_times = [record.ts for record in can_send.tx_log()]
        self.assertTrue(all(right - left >= 0.045 for left, right in zip(tx_times, tx_times[1:])))

        connection.fail_message = "bus failed"
        failed = context.send_pgn(0xFECA, bytes(range(15)), source_address=0x80,
                                 destination_address=0x0B)
        with self.assertRaisesRegex(RuntimeError, "bus failed"):
            failed.result()
        self.assertEqual(connection.requested[-1].data[0], 0xFF)
        self.assertEqual(len(can_send.tx_log()), 6)
        can_send.shutdown()

    def test_wait_for_returns_future_without_waiting_in_caller(self):
        connection = _Connection()
        context = _PluginContext(SimpleNamespace(connection_vm=connection))
        future = context.wait_for(0xFECA, 0x0A, 0.01)
        self.assertTrue(context._chunk_listener_connected)
        with self.assertRaises(TimeoutError):
            context._expire_wait(next(iter(context._operations)))
            future.result()
        self.assertFalse(context._chunk_listener_connected)

    def test_wait_for_receives_simulated_response(self):
        connection = _Connection()
        context = _PluginContext(SimpleNamespace(connection_vm=connection))
        future = context.wait_for(0xFECA, 0x0A, 1.0)
        self.assertTrue(context._chunk_listener_connected)
        callback_threads = []
        future.add_done_callback(lambda _done: callback_threads.append(QThread.currentThread()))
        context._record_transport_frames(pl.DataFrame({
            "TS": [1.0], "ID": ["18FECA0A"], "DATA": ["010203"]
        }))
        self.app.processEvents()
        self.assertTrue(future.done())
        response = future.result()
        self.assertEqual(response.source_address, 0x0A)
        self.assertEqual(response.data, b"\x01\x02\x03")
        self.assertEqual(callback_threads, [QThread.currentThread()])
        self.assertFalse(context._chunk_listener_connected)

    def test_wait_for_reassembles_bam_and_cmdt_responses(self):
        for destination in (0xFF, 0x80):
            connection = _Connection()
            context = _PluginContext(SimpleNamespace(connection_vm=connection))
            payload = bytes(range(20))
            frames = build_transport_frames(0xFECA, payload, 0x0A, destination)
            rows = [(float(index), f"{frame.can_id:08X}", frame.data.hex().upper())
                    for index, frame in enumerate(frames)]
            if destination != 0xFF:
                rows.insert(1, (0.1, "18EC0A80", "110301FFFFCAFE00"))
            future = context.wait_for(0xFECA, 0x0A, 1.0)
            context._record_transport_frames(pl.DataFrame(
                rows, schema=[("TS", pl.Float64), ("ID", pl.String), ("DATA", pl.String)], orient="row"
            ))
            self.assertTrue(future.done(), f"response not reassembled for destination {destination}")
            response = future.result()
            self.assertEqual(response.data, payload)
            self.assertEqual(response.source_address, 0x0A)

    def test_wait_for_cancellation_is_immediate_and_all_waits_are_registered(self):
        connection = _Connection()
        context = _PluginContext(SimpleNamespace(connection_vm=connection))
        futures = [context.wait_for(0xFECA + index, None, 2.0) for index in range(5)]
        self.assertEqual(len(context._operations), 5)
        self.assertTrue(futures[-1].cancel())
        self.app.processEvents()
        self.assertEqual(len(context._operations), 4)
        for future in futures[:-1]:
            future.cancel()
        self.app.processEvents()
        self.assertEqual(context._operations, {})
        self.assertFalse(context._chunk_listener_connected)

    def test_plugin_unload_cancels_its_waits(self):
        context = _PluginContext(SimpleNamespace(connection_vm=_Connection()))
        future = context.scoped("plugin-owner").wait_for(0xFECA, None, 10.0)
        context.unsubscribe_owner("plugin-owner")
        self.assertTrue(future.cancelled())
        self.assertEqual(context._operations, {})
        self.assertFalse(context._chunk_listener_connected)


if __name__ == "__main__":
    unittest.main()
