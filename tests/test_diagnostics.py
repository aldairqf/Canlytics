from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import polars as pl
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from services.error_diagnostics import ErrorDiagnosticsSnapshot
from services.can_data_parser import frame_dict, rows_to_df
from services.can_data_parser import load_can_dataframe
from viewmodels.diagnostics_viewmodel import DiagnosticsViewModel
from viewmodels.diagnostics_history_worker import filter_diagnostic_rows
from viewmodels.diagnostics_history_worker import DiagnosticsHistoryWorker
from views.diagnostics_window import DiagnosticsWindow
from views.diagnostics_window_manager import DiagnosticsWindowManager


class _Connection(QObject):
    error_frame_received = Signal(object)
    transport_error = Signal(str)
    application_error = Signal(str)
    chunk_ready = Signal(object)
    running_changed = Signal(bool)


class _Sender(QObject):
    tx_log_appended = Signal(object)
    def __init__(self):
        super().__init__()
        self.sent = []

    def send_plugin_frame(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return "tx-1"


class DiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_viewmodel_observes_chunk_and_builds_active_requests(self):
        connection = _Connection()
        sender = _Sender()
        vm = DiagnosticsViewModel(connection, sender)
        chunk = pl.DataFrame({"TS": [0.0], "ID": ["7E8"], "DATA": ["0322F190"]})
        vm.ingest_chunk(chunk)
        self.assertEqual(vm.messages[-1]["protocol"], "UDS")
        vm.request_obd_pid(0x0C)
        vm.request_j1939_pgn(0xF004)
        self.assertEqual(len(sender.sent), 2)
        self.assertEqual(sender.sent[0][0][0], 0x7DF)
        self.assertTrue(sender.sent[1][1]["extended"])

    def test_ingest_chunk_ignores_non_diagnostic_traffic_and_continues_after_invalid_sf(self):
        connection = _Connection()
        vm = DiagnosticsViewModel(connection, _Sender())
        chunk = rows_to_df([
            frame_dict(ts=0.0, bus="b", can_id="18FEF100", data=bytes.fromhex("0412FF0000000000")),
            frame_dict(ts=0.01, bus="b", can_id="CF00400", data=bytes.fromhex("05AA112233445566")),
            frame_dict(ts=0.02, bus="b", can_id="123", data=bytes.fromhex("0011223344556677")),
            frame_dict(ts=0.03, bus="b", can_id="7E8", data=bytes.fromhex("0250030000000000")),
        ])

        vm.ingest_chunk(chunk)

        self.assertEqual(len(vm.messages), 1)
        self.assertEqual(vm.messages[0]["protocol"], "UDS")
        self.assertEqual(vm.messages[0]["sid"], 0x50)

    def test_uds_positive_response_pending_and_obd_mode_classification(self):
        vm = DiagnosticsViewModel(_Connection(), _Sender())
        rows = [
            frame_dict(ts=0.0, bus="b", can_id="7E8", data=bytes.fromhex("0250030000000000")),
            frame_dict(ts=0.1, bus="b", can_id="7E8", data=bytes.fromhex("037F227800000000")),
            frame_dict(ts=0.2, bus="b", can_id="7E8", data=bytes.fromhex("03410C0000000000")),
        ]
        vm.ingest_chunk(rows_to_df(rows))

        self.assertEqual([item["protocol"] for item in vm.messages], ["UDS", "UDS", "OBD"])
        self.assertTrue(vm.messages[0]["positive"])
        self.assertTrue(vm.messages[1]["response_pending"])
        self.assertEqual(vm.messages[1]["nrc"], 0x78)
        self.assertEqual(vm.messages[2]["mode"], 1)

    def test_log_source_reset_rebuilds_observer_with_configured_timeout(self):
        vm = DiagnosticsViewModel(_Connection(), _Sender())
        vm.ingest_error_record({"type": "candump_error_flag", "TS": 1.0})
        vm.reset_for_source()

        self.assertEqual(vm.snapshot.total, 0)
        self.assertEqual(vm.transport_errors, 0)
        self.assertEqual(vm.messages, [])

    def test_j1939_request_uses_configured_source_address_and_three_byte_payload(self):
        sender = _Sender()
        vm = DiagnosticsViewModel(_Connection(), sender)

        vm.request_j1939_pgn(0xF004)

        can_id = sender.sent[0][0][0]
        payload = sender.sent[0][0][1]
        self.assertEqual(payload, bytes.fromhex("04F000"))
        self.assertEqual(can_id & 0xFF, 0xF9)

    def test_error_frames_are_counted_by_can_error_class(self):
        vm = DiagnosticsViewModel(_Connection(), _Sender())
        vm.ingest_error_record({
            "type": "candump_error_flag", "TS": 1.0, "ID": 0x20000163,
            "error_id": 0x20000163, "data": bytes((0, 0, 0, 0, 0, 0, 0, 0)),
        })
        counts = vm.snapshot.counts
        classes = vm.snapshot.classes
        for name in ("ack", "bus_off", "lost_arbitration", "restarted"):
            self.assertEqual(classes[name], 1)
        self.assertEqual(vm.snapshot.total, 1)

    def test_offscreen_window_delete_attribute_and_error_summary(self):
        class _FakeVM(QObject):
            changed = Signal(object, object)
            message_observed = Signal(object)
            history_loaded = Signal(object)
            def __init__(self):
                super().__init__()
                self.snapshot = ErrorDiagnosticsSnapshot({}, 0, 0.0)
                self.transport_errors = 0
                self.application_errors = 0
        vm = _FakeVM()
        window = DiagnosticsWindow(vm)
        self.assertTrue(window.testAttribute(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WidgetAttribute.WA_DeleteOnClose))
        self.assertIn("Bus errors", window._errors.text())
        window.close()

    def test_manager_subscribes_only_while_window_is_open(self):
        connection = _Connection()
        vm = DiagnosticsViewModel(connection, _Sender())
        manager = DiagnosticsWindowManager(vm, connection)
        window = manager.open_window()
        self.assertIsNotNone(manager._chunk_connection)
        window.close()
        self.app.processEvents()
        self.assertIsNone(manager._chunk_connection)

    def test_window_reopen_renders_existing_diagnostic_history(self):
        vm = DiagnosticsViewModel(_Connection(), _Sender())
        vm.ingest_chunk(rows_to_df([
            frame_dict(ts=0.0, bus="b", can_id="7E8", data=bytes.fromhex("0250030000000000")),
        ]))

        window = DiagnosticsWindow(vm)

        self.assertEqual(window._messages.rowCount(), 1)
        window.close()

    def test_window_batches_message_inserts_until_flush(self):
        vm = DiagnosticsViewModel(_Connection(), _Sender())
        window = DiagnosticsWindow(vm)
        message = {"protocol": "UDS", "can_id": 0x7E8, "sid": 0x50, "payload": "50 00"}
        window._append_message(message)
        self.assertEqual(window._messages.rowCount(), 0)
        window._flush_updates()
        self.assertEqual(window._messages.rowCount(), 1)
        window.close()

    def test_window_displays_nrc_and_response_pending(self):
        vm = DiagnosticsViewModel(_Connection(), _Sender())
        window = DiagnosticsWindow(vm)
        window._append_message({"protocol": "UDS", "can_id": 0x7E8, "sid": 0x22,
                                "negative": True, "nrc": 0x78,
                                "classification": "response pending", "payload": "7F 22 78"})
        window._flush_updates()
        self.assertEqual(window._messages.item(0, 2).text(), "NRC 0x78 (Response pending)")
        window.close()

    def test_loaded_candump_populates_obd_and_uds_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics.log"
            path.write_text(
                "(0.0) can0 123#0322F190\n"
                "(0.1) can0 7DF#0201000000000000\n"
                "(0.2) can0 7E8#064100BE3FA81300\n"
                "(0.3) can0 7E0#0322F19000000000\n"
                "(0.4) can0 7E8#037F227800000000\n",
                encoding="utf-8",
            )
            dataframe = load_can_dataframe(path)
            result = []
            worker = DiagnosticsHistoryWorker(dataframe, 1.0, [], 100)
            worker.finished.connect(result.extend)
            worker.run()

        items = result
        self.assertEqual([item["protocol"] for item in items], ["OBD", "OBD", "UDS", "UDS"])
        self.assertEqual((items[0]["mode"], items[0]["pid"]), (1, 0))
        self.assertEqual((items[1]["mode"], items[1]["pid"]), (1, 0))
        self.assertEqual(items[3]["nrc"], 0x78)
        self.assertTrue(items[3]["response_pending"])

    def test_window_updates_when_loaded_history_finishes(self):
        vm = DiagnosticsViewModel(_Connection(), _Sender())
        window = DiagnosticsWindow(vm)
        messages = [
            {"protocol": "OBD", "can_id": 0x7DF, "mode": 1, "pid": 0, "payload": "01 00"},
            {"protocol": "OBD", "can_id": 0x7E8, "mode": 1, "pid": 0, "payload": "41 00"},
            {"protocol": "UDS", "can_id": 0x7E0, "sid": 0x22, "payload": "22 F1 90"},
            {"protocol": "UDS", "can_id": 0x7E8, "sid": 0x22, "negative": True,
             "nrc": 0x78, "response_pending": True, "payload": "7F 22 78"},
        ]

        vm.history_loaded.emit(messages)
        window._flush_updates()

        self.assertEqual(window._messages.rowCount(), 4)
        self.assertIn("Mode 01 PID 00", window._messages.item(0, 2).text())
        self.assertIn("Mode 01 PID 00", window._messages.item(1, 2).text())
        self.assertIn("UDS 0x22", window._messages.item(2, 2).text())
        self.assertIn("NRC 0x78", window._messages.item(3, 2).text())
        window.close()

    def test_history_filter_includes_configured_and_extended_ids(self):
        dataframe = rows_to_df([
            frame_dict(ts=0.0, bus="b", can_id="123", data=b"\x03\x22\xf1\x90"),
            frame_dict(ts=0.1, bus="b", can_id="18DAF110", data=b"\x03\x22\xf1\x90"),
            frame_dict(ts=0.2, bus="b", can_id="18DB33F1", data=b"\x03\x22\xf1\x90"),
            frame_dict(ts=0.3, bus="b", can_id="456", data=b"\x03\x22\xf1\x90"),
        ])
        filtered = filter_diagnostic_rows(dataframe, ["456"])
        self.assertEqual(filtered["ID"].to_list(), ["18DAF110", "18DB33F1", "456"])

    def test_diagnostics_table_stretches_payload_column(self):
        from PySide6.QtWidgets import QHeaderView
        window = DiagnosticsWindow(DiagnosticsViewModel(_Connection(), _Sender()))
        self.assertEqual(window._messages.horizontalHeader().sectionResizeMode(3),
                         QHeaderView.ResizeMode.Stretch)
        window.close()


if __name__ == "__main__":
    unittest.main()
