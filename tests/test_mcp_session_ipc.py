from __future__ import annotations

import json
import asyncio
import os
import sys
import tempfile
import time
import unittest
from multiprocessing.connection import AuthenticationError, Client as PipeClient
from pathlib import Path
from unittest.mock import patch

import polars as pl
from PySide6.QtCore import QCoreApplication
from mcp import Client, StdioServerParameters

from mcp_server.session_client import McpSessionClient, McpSessionUnavailable
from models.analysis_context import AnalysisContext
from services.session_state import SessionStateStore
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
