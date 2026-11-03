from __future__ import annotations

import json
import asyncio
import os
import sys
import threading
import tempfile
import time
import unittest
from multiprocessing.connection import AuthenticationError, Client as PipeClient
from pathlib import Path
from unittest.mock import patch

import polars as pl
import cantools
from PySide6.QtCore import QCoreApplication
from mcp import Client, StdioServerParameters

from mcp_server.session_client import McpSessionClient, McpSessionUnavailable
from models.analysis_context import AnalysisContext
from services.session_state import SessionStateStore
from services.working_dbc import WorkingDbc
from viewmodels.main_window_viewmodel import MainWindowViewModel
from viewmodels.mcp_session_viewmodel import McpSessionViewModel


class McpSessionIpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="canlytics-mcp-session-")
        self.endpoint = Path(self._temporary.name) / "session-endpoint.json"
        self.view_model = McpSessionViewModel(endpoint_path=self.endpoint)
        self.client = McpSessionClient(endpoint_path=self.endpoint, timeout=1.0)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not self.view_model.ready:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(self.view_model.ready, "MCP session endpoint did not start")

    def tearDown(self) -> None:
        self.view_model.shutdown()
        self.assertFalse(self.view_model.thread_running)
        self.assertFalse(self.endpoint.exists())
        self._temporary.cleanup()

    def _load_snapshot(self) -> None:
        self.view_model.snapshot.replace_dataframe(
            pl.DataFrame(
                [(1.0, "can0", "100", 1, "AA"), (2.0, "can0", "100", 1, "BB")],
                schema=["TS", "Bus", "ID", "LEN", "DATA"],
                orient="row",
            ),
            can_ids=["100"],
            source_paths=["/logs/sample.log"],
            unsaved=True,
            connection_running=True,
        )

    def test_client_reads_status_frames_context_and_markers(self) -> None:
        self._load_snapshot()
        status = self.client.get_open_session()
        self.assertTrue(status["connected"])
        self.assertEqual(status["frame_count"], 2)
        self.assertEqual(status["source_paths"], ["/logs/sample.log"])
        self.assertEqual(self.client.get_recent_frames(limit=1)["frames"][0]["DATA"], "BB")
        self.assertEqual(self.client.get_analysis_context(), {"context": None})
        self.assertEqual(self.client.add_session_marker("key on")["marker"]["timestamp"], 2.0)
        self.assertEqual(len(self.client.list_session_markers()["markers"]), 1)

    def test_session_server_rejects_bad_authentication_and_unknown_methods(self) -> None:
        descriptor = json.loads(self.endpoint.read_text(encoding="utf-8"))
        with self.assertRaises(AuthenticationError):
            PipeClient(descriptor["address"], family=descriptor["family"], authkey=b"wrong-key")
        with self.assertRaisesRegex(ValueError, "Unknown MCP session method"):
            self.client.request("unknown_method")

    def test_actions_are_dispatched_on_the_viewmodel_thread(self) -> None:
        gui_thread = threading.get_ident()
        calls = []
        action_vm = McpSessionViewModel(
            endpoint_path=Path(self._temporary.name) / "action-session.json",
            action_handler=lambda method, params: calls.append((threading.get_ident(), method, params)) or {"ok": True},
        )
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not action_vm.ready:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(action_vm.ready)
        client = McpSessionClient(endpoint_path=action_vm.endpoint_path, timeout=2.0)
        result = []
        errors = []

        def request_action() -> None:
            try:
                result.append(client.request("decode_with_dbc", {"can_id": "100", "data_hex": "00"}))
            except Exception as exc:
                errors.append(exc)

        requester = threading.Thread(target=request_action)
        requester.start()
        deadline = time.monotonic() + 3.0
        while requester.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        requester.join(timeout=0.2)
        try:
            self.assertFalse(requester.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result, [{"ok": True}])
            self.assertEqual(calls[0][0], gui_thread)
        finally:
            action_vm.shutdown()

    def test_timed_out_action_is_cancelled_before_the_gui_processes_it(self) -> None:
        calls = []
        action_vm = McpSessionViewModel(
            endpoint_path=Path(self._temporary.name) / "timeout-session.json",
            action_handler=lambda method, params: calls.append(method) or {"ok": True},
        )
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not action_vm.ready:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(action_vm.ready)
        client = McpSessionClient(endpoint_path=action_vm.endpoint_path, timeout=2.0)
        errors = []

        def request_action() -> None:
            try:
                client.request("save_signal_to_working_dbc", {"can_id": "100"})
            except Exception as exc:
                errors.append(exc)

        try:
            with patch("viewmodels.mcp_session_viewmodel._ACTION_REQUEST_TIMEOUT_SECONDS", 0.05):
                requester = threading.Thread(target=request_action)
                requester.start()
                requester.join(timeout=1.0)
                self.assertFalse(requester.is_alive())
            self.app.processEvents()
            self.assertTrue(errors)
            self.assertEqual(calls, [])
        finally:
            action_vm.shutdown()

    def test_started_action_finishes_before_the_worker_returns_timeout(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls = []
        action_vm = McpSessionViewModel(
            endpoint_path=Path(self._temporary.name) / "started-session.json",
            action_handler=lambda method, params: (
                calls.append(method), started.set(), release.wait(1.0), {"ok": True}
            )[-1],
        )
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not action_vm.ready:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(action_vm.ready)
        client = McpSessionClient(endpoint_path=action_vm.endpoint_path, timeout=2.0)
        results = []
        errors = []

        def request_action() -> None:
            try:
                results.append(client.request("decode_with_dbc", {"can_id": "100", "data_hex": "00"}))
            except Exception as exc:
                errors.append(exc)

        try:
            with patch("viewmodels.mcp_session_viewmodel._ACTION_REQUEST_TIMEOUT_SECONDS", 0.05):
                requester = threading.Thread(target=request_action)
                requester.start()
                threading.Timer(0.15, release.set).start()
                deadline = time.monotonic() + 1.0
                while not started.is_set() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.assertTrue(started.is_set())
                while requester.is_alive():
                    self.app.processEvents()
                    time.sleep(0.01)
                requester.join(timeout=0.2)
            self.assertEqual(errors, [])
            self.assertEqual(results, [{"ok": True}])
            self.assertEqual(calls, ["decode_with_dbc"])
        finally:
            release.set()
            action_vm.shutdown()

    def test_stdio_dbc_tools_decode_and_persist_working_signal(self) -> None:
        root_endpoint = Path(self._temporary.name) / "root-session.json"
        store = SessionStateStore(root=Path(self._temporary.name) / "state")
        with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
            root = MainWindowViewModel(
                enable_mcp_session=True,
                mcp_session_endpoint_path=root_endpoint,
            )
        root.working_dbc.create_message("Status", 0x123, length=2)
        root.working_dbc.create_signal(0x123, "Existing", start=0, length=8)
        root.save_working_dbc()

        async def query_tools() -> dict:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "mcp_server"],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "CANLYTICS_MCP_SESSION_FILE": str(root_endpoint)},
            )
            async with Client(parameters) as mcp_client:
                decoded = await mcp_client.call_tool("decode_with_dbc", {"can_id": "123", "data_hex": "2A00"})
                rejected_fd = await mcp_client.call_tool(
                    "decode_with_dbc", {"can_id": "123", "data_hex": "000000000000000000"},
                )
                rejected_id = await mcp_client.call_tool(
                    "decode_with_dbc", {"can_id": "-1", "data_hex": "00"},
                )
                failed_save = await mcp_client.call_tool("save_signal_to_working_dbc", {
                    "can_id": "124", "signal_name": "OutOfBounds", "start": 64, "length": 8,
                })
                saved = await mcp_client.call_tool("save_signal_to_working_dbc", {
                    "can_id": "123", "signal_name": "NewSignal", "start": 8, "length": 8,
                })
            return {
                "decoded": decoded,
                "rejected_fd": rejected_fd,
                "rejected_id": rejected_id,
                "failed_save": failed_save,
                "saved": saved,
            }

        result = []
        errors = []

        def run_client() -> None:
            try:
                result.append(asyncio.run(query_tools()))
            except Exception as exc:
                errors.append(exc)

        client_thread = threading.Thread(target=run_client)
        try:
            client_thread.start()
            deadline = time.monotonic() + 10.0
            while client_thread.is_alive() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            client_thread.join(timeout=0.2)
            self.assertFalse(client_thread.is_alive(), "stdio DBC tool call did not finish")
            self.assertEqual(errors, [])
            self.assertFalse(result[0]["decoded"].is_error)
            decoded_result = result[0]["decoded"]
            decoded = decoded_result.structured_content
            if decoded is None:
                decoded = json.loads(decoded_result.content[0].text)
            decoded = decoded.get("result", decoded)
            self.assertEqual(decoded["message_name"], "Status")
            self.assertEqual(decoded["signals"][0]["name"], "Existing")
            self.assertTrue(result[0]["rejected_fd"].is_error)
            self.assertTrue(result[0]["rejected_id"].is_error)
            self.assertTrue(result[0]["failed_save"].is_error)
            with self.assertRaises(KeyError):
                root.working_dbc.get_message(0x124)
            self.assertFalse(result[0]["saved"].is_error)
            self.assertTrue(store.working_dbc_path.exists())
            self.assertEqual(
                [signal.name for signal in root.dbc_manager.resolve_message("123")[1].signals],
                ["Existing", "NewSignal"],
            )
        finally:
            if client_thread.is_alive():
                client_thread.join(timeout=1.0)
            root.shutdown()

    def test_save_signal_rekeys_a_j1939_message_to_the_requested_source_address(self) -> None:
        store = SessionStateStore(root=Path(self._temporary.name) / "j1939-state")
        with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
            root = MainWindowViewModel()
        source = WorkingDbc()
        message = source.create_message("EngineData", 0x18F00401, length=8, is_extended_frame=True)
        source.create_signal(message.frame_id, "Existing", start=0, length=8)
        root.dbc_manager.add_loaded_db(
            str(Path(self._temporary.name) / "j1939.dbc"),
            source.database_copy(),
            preferred_name="J1939",
            mode="j1939",
        )
        try:
            root.handle_mcp_session_action("save_signal_to_working_dbc", {
                "can_id": "18F00422", "signal_name": "NewSignal", "start": 8, "length": 8,
            })
            copied = root.working_dbc.get_message(0x18F00422)
            self.assertEqual(
                [signal.name for signal in copied.signals],
                ["Existing", "NewSignal"],
            )
            self.assertEqual(root.dbc_manager.resolve_message("18F00422")[1].frame_id, 0x18F00422)
        finally:
            root.shutdown()

    def test_decode_rejects_bam_messages_that_need_reassembly(self) -> None:
        store = SessionStateStore(root=Path(self._temporary.name) / "bam-state")
        with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
            root = MainWindowViewModel()
        pgn_frame = 0x18F00401
        long_message = cantools.database.can.Message(
            frame_id=pgn_frame,
            name="LongPayload",
            length=9,
            signals=[],
            is_extended_frame=True,
        )
        db = cantools.database.Database(messages=[long_message], strict=False)
        root.dbc_manager.add_loaded_db(
            str(Path(self._temporary.name) / "bam.dbc"),
            db,
            preferred_name="BAM",
            mode="j1939",
        )
        try:
            with self.assertRaisesRegex(ValueError, "does not reassemble"):
                root.handle_mcp_session_action("decode_with_dbc", {
                    "can_id": f"{pgn_frame:X}", "data_hex": "0000000000000000",
                })
        finally:
            root.shutdown()

    def test_failed_save_rolls_back_signal_added_to_existing_message(self) -> None:
        store = SessionStateStore(root=Path(self._temporary.name) / "rollback-state")
        with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
            root = MainWindowViewModel()
        root.working_dbc.create_message("Status", 0x222, length=2)
        root.working_dbc.create_signal(0x222, "Existing", start=0, length=8)
        try:
            with patch.object(root, "save_working_dbc", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    root.handle_mcp_session_action("save_signal_to_working_dbc", {
                        "can_id": "222", "signal_name": "Transient", "start": 8, "length": 8,
                    })
            self.assertEqual(
                [signal.name for signal in root.working_dbc.get_message(0x222).signals],
                ["Existing"],
            )
        finally:
            root.shutdown()

    def test_missing_endpoint_is_reported_without_failing_open_session_tool(self) -> None:
        self.view_model.shutdown()
        result = self.client.get_open_session()
        self.assertFalse(result["connected"])

    def test_main_window_composition_publishes_loaded_log_live_delta_and_context(self) -> None:
        root_endpoint = Path(self._temporary.name) / "root-session.json"
        store = SessionStateStore(root=Path(self._temporary.name) / "state")
        with patch("viewmodels.main_window_viewmodel.SessionStateStore", return_value=store):
            root = MainWindowViewModel(
                enable_mcp_session=True,
                mcp_session_endpoint_path=root_endpoint,
            )
        try:
            fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "logs" / "candump-sample.log"
            root.data_vm.load_log(str(fixture))
            root.analysis_context_vm.set_context(
                AnalysisContext(can_id=root.data_vm.can_ids[0], byte_indices=(0,), source_window="Analyze")
            )
            client = McpSessionClient(endpoint_path=root_endpoint, timeout=1.0)
            status = client.get_open_session()
            self.assertEqual(status["frame_count"], root.data_vm.df.height)
            self.assertIn(root.data_vm.can_ids[0], status["can_ids"])
            self.assertEqual(client.get_analysis_context()["context"]["source_window"], "Analyze")

            async def query_mcp_process() -> dict:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "mcp_server"],
                    cwd=Path(__file__).resolve().parents[1],
                    env={**os.environ, "CANLYTICS_MCP_SESSION_FILE": str(root_endpoint)},
                )
                async with Client(parameters) as mcp_client:
                    session = await mcp_client.call_tool("get_open_session")
                    frames = await mcp_client.call_tool("get_recent_frames", {"limit": 2})
                    marker = await mcp_client.call_tool("add_session_marker", {"name": "door opened"})
                self.assertFalse(session.is_error)
                self.assertFalse(frames.is_error)
                self.assertFalse(marker.is_error)
                payload = session.structured_content
                if payload is None:
                    payload = json.loads(session.content[0].text)
                return payload.get("result", payload)

            with patch.dict(os.environ, {"CANLYTICS_MCP_SESSION_FILE": str(root_endpoint)}):
                process_session = asyncio.run(query_mcp_process())
            self.assertEqual(process_session["frame_count"], status["frame_count"])

            root.data_vm.append_df(root.data_vm.df.tail(1))
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and root.data_vm.df.height == status["frame_count"]:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertEqual(client.get_open_session()["frame_count"], status["frame_count"] + 1)
            self.assertEqual(len(client.list_session_markers()["markers"]), 1)
        finally:
            root.shutdown()
        self.assertFalse(root_endpoint.exists())


if __name__ == "__main__":
    unittest.main()
