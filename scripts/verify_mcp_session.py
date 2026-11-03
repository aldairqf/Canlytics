from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication
from mcp import Client, StdioServerParameters

from mcp_server.session_client import McpSessionClient
from models.analysis_context import AnalysisContext
from viewmodels.main_window_viewmodel import MainWindowViewModel


def main() -> None:
    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    repo = Path(__file__).resolve().parents[1]
    fixture = repo / "tests" / "fixtures" / "logs" / "candump-sample.log"
    fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    previous_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="canlytics-mcp-session-verify-") as temporary:
        os.chdir(temporary)
        endpoint = Path(temporary) / "session-endpoint.json"
        vm = MainWindowViewModel(
            enable_mcp_session=True,
            mcp_session_endpoint_path=endpoint,
        )
        try:
            vm.data_vm.load_log(str(fixture))
            can_id = vm.data_vm.can_ids[0]
            vm.analysis_context_vm.set_context(
                AnalysisContext(can_id=can_id, byte_indices=(0, 1), source_window="Analyze")
            )
            deadline = time.monotonic() + 3.0
            client = McpSessionClient(endpoint_path=endpoint, timeout=1.0)
            session = client.get_open_session()
            while time.monotonic() < deadline and not session.get("connected"):
                app.processEvents()
                time.sleep(0.01)
                session = client.get_open_session()
            if not session.get("connected"):
                raise RuntimeError(session.get("message", "MCP session did not start"))

            async def query_mcp_process() -> tuple[dict, dict, dict, dict]:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "mcp_server"],
                    cwd=repo,
                    env={**os.environ, "CANLYTICS_MCP_SESSION_FILE": str(endpoint)},
                )
                async with Client(parameters) as mcp_client:
                    status = await mcp_client.call_tool("get_open_session")
                    frames = await mcp_client.call_tool("get_recent_frames", {"limit": 3})
                    context = await mcp_client.call_tool("get_analysis_context")
                    marker = await mcp_client.call_tool("add_session_marker", {"name": "verify event"})
                for response in (status, frames, context, marker):
                    if response.is_error:
                        raise RuntimeError(response.content[0].text)
                return tuple(
                    response.structured_content["result"]
                    if response.structured_content is not None
                    else json.loads(response.content[0].text)
                    for response in (status, frames, context, marker)
                )

            status, recent, context, marker = asyncio.run(query_mcp_process())
            if status["frame_count"] != vm.data_vm.df.height or not recent["frames"]:
                raise AssertionError("MCP did not return the open log frames")
            if context["context"]["can_id"] != can_id or marker["marker"]["name"] != "verify event":
                raise AssertionError("MCP did not preserve context or add a session marker")
            original_count = vm.data_vm.df.height
            vm.data_vm.append_df(vm.data_vm.df.tail(1))
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and vm.data_vm.df.height == original_count:
                app.processEvents()
                time.sleep(0.01)
            if client.get_open_session()["frame_count"] != original_count + 1:
                raise AssertionError("The live session delta was not published")
        finally:
            vm.shutdown()
            os.chdir(previous_cwd)
        if endpoint.exists() or vm.mcp_session_vm.thread_running:
            raise AssertionError("MCP session endpoint or worker survived app shutdown")
    if hashlib.sha256(fixture.read_bytes()).hexdigest() != fixture_hash:
        raise AssertionError("The fixture log changed during verification")
    print("MCP session smoke passed: stdio process, frames, context, marker, delta, and shutdown")


if __name__ == "__main__":
    main()
