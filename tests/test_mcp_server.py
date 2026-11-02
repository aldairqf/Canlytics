from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import can
from mcp import Client, StdioServerParameters

from mcp_server.server import build_server
from mcp_server.tools import CanlyticsTools


class CanlyticsToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "field.log"
        self.source.write_text(
            "(1.000000) can0 100#0000000000000001\n"
            "(2.000000) can0 100#0000000000000002\n"
            "(3.000000) can1 101#0000000000000003\n"
            "(4.000000) can0 100#0000000000000004\n",
            encoding="utf-8",
        )
        self.original_source = self.source.read_bytes()
        self.output = root / "mcp-output"
        self.tools = CanlyticsTools(output_dir=self.output)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_load_log_and_inspect_ids_and_stats_without_modifying_source(self) -> None:
        summary = self.tools.load_log(str(self.source))
        self.assertEqual(summary["frames"], 4)
        self.assertEqual(summary["ids"], 2)
        self.assertEqual(self.tools.list_ids(), ["100", "101"])
        stats = self.tools.id_stats("0x100")
        self.assertEqual(stats["frames"], 3)
        self.assertEqual(stats["buses"], ["can0"])
        self.assertEqual(self.source.read_bytes(), self.original_source)

    def test_analysis_tools_reuse_candidate_and_range_diff_services(self) -> None:
        self.tools.load_log(str(self.source))
        candidates = self.tools.find_candidates(["100"], limit=5)
        self.assertTrue(candidates)
        self.assertTrue(all(item["can_id"] == "100" for item in candidates))
        diff = self.tools.diff_ranges(1.0, 2.0, 3.0, 4.0)
        self.assertTrue(diff["ids"])
        self.assertEqual(diff["range_a"], {"start": 1.0, "end": 2.0})

    def test_constraint_search_validates_normalized_targets(self) -> None:
        self.tools.load_log(str(self.source))
        with self.assertRaises(ValueError):
            self.tools.constraint_search([{"time_abs": 2.0, "target_norm": 1.5}], ["100"])
        result = self.tools.constraint_search(
            [{"time_abs": 2.0, "target_norm": 0.5}], ["100"], limit=5,
        )
        self.assertIn("results", result)
        self.assertIn("exclusions", result)

    def test_writes_export_and_artifacts_only_under_mcp_output_folder(self) -> None:
        self.tools.load_log(str(self.source))
        exported = self.tools.export_log("copy.log")
        filtered = self.tools.export_log("filtered.log", scope="filtered", can_ids=["0x100"])
        signals = self.tools.save_signals("signals.json", [{"name": "speed", "can_id": "100"}])
        markers = self.tools.save_markers("markers.json", [{"name": "start", "timestamp": 1.0}])
        self.assertTrue(Path(exported["path"]).is_relative_to(self.output))
        self.assertEqual(filtered["frames"], 3)
        self.assertTrue(Path(signals["path"]).is_relative_to(self.output))
        self.assertTrue(Path(markers["path"]).is_relative_to(self.output))
        self.assertEqual(json.loads(Path(signals["path"]).read_text(encoding="utf-8"))["signals"][0]["name"], "speed")
        self.assertEqual(self.source.read_bytes(), self.original_source)

    def test_rejects_output_paths_that_escape_the_mcp_folder(self) -> None:
        self.tools.load_log(str(self.source))
        with self.assertRaises(ValueError):
            self.tools.save_markers("../field.log", [{"name": "bad", "timestamp": 1.0}])
        with self.assertRaises(ValueError):
            self.tools.export_log(str(self.source))
        self.assertEqual(self.source.read_bytes(), self.original_source)

    def test_can_transmit_is_disabled_by_default(self) -> None:
        with patch.object(can, "Bus") as bus_factory:
            with self.assertRaises(PermissionError):
                self.tools.send_frame("vcan0", 0x123, "AABB", interface="socketcan")
        bus_factory.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_enabled_can_transmit_records_each_attempt(self) -> None:
        tools = CanlyticsTools(output_dir=self.output, allow_can_send=True)
        with patch.object(can, "Bus") as bus_factory:
            result = tools.send_frame("vcan0", 0x123, "AABB", interface="socketcan")
        bus_factory.return_value.send.assert_called_once()
        bus_factory.return_value.shutdown.assert_called_once()
        self.assertEqual(result["status"], "sent")
        records = [json.loads(line) for line in (self.output / "tx-log.jsonl").read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data"], "AABB")

    def test_tx_log_cannot_overwrite_loaded_source(self) -> None:
        tools = CanlyticsTools(
            output_dir=self.source.parent,
            tx_log_path=self.source,
            allow_can_send=True,
        )
        tools.load_log(str(self.source))
        with patch.object(can, "Bus") as bus_factory:
            with self.assertRaises(PermissionError):
                tools.send_frame("vcan0", 0x123, "AABB")
        bus_factory.assert_not_called()
        self.assertEqual(self.source.read_bytes(), self.original_source)

    def test_failed_bus_attempt_is_recorded_in_tx_log(self) -> None:
        tools = CanlyticsTools(output_dir=self.output, allow_can_send=True)
        with patch.object(can, "Bus", side_effect=RuntimeError("bus unavailable")):
            with self.assertRaisesRegex(RuntimeError, "bus unavailable"):
                tools.send_frame("can0", 0x123, "AABB")
        records = [json.loads(line) for line in (self.output / "tx-log.jsonl").read_text().splitlines()]
        self.assertEqual(records[0]["status"], "error")
        self.assertEqual(records[0]["error"], "bus unavailable")


class McpServerRegistrationTests(unittest.TestCase):
    def test_send_tool_is_registered_only_when_explicitly_enabled(self) -> None:
        default_server = build_server()
        enabled_server = build_server(allow_can_send=True)
        default_tools = {tool.name for tool in asyncio.run(default_server.list_tools())}
        enabled_tools = {tool.name for tool in asyncio.run(enabled_server.list_tools())}
        self.assertNotIn("send_frame", default_tools)
        self.assertIn("send_frame", enabled_tools)
        self.assertTrue({
            "load_log", "list_ids", "id_stats", "find_candidates", "diff_ranges",
            "constraint_search", "export_log", "save_signals", "save_markers",
        } <= default_tools)

    def test_stdio_process_lists_tools_and_keeps_loaded_log_session(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.log"
            source.write_text("(1.0) can0 123#AABB\n", encoding="utf-8")

            async def exercise_stdio() -> None:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "mcp_server"],
                    cwd=root,
                )
                async with Client(parameters) as client:
                    listed_tools = (await client.list_tools()).tools
                    tools = {tool.name for tool in listed_tools}
                    self.assertIn("load_log", tools)
                    self.assertNotIn("send_frame", tools)
                    constraint_schema = next(
                        tool.input_schema for tool in listed_tools if tool.name == "constraint_search"
                    )
                    self.assertIn("time_abs", json.dumps(constraint_schema))
                    loaded = await client.call_tool("load_log", {"path": str(source)})
                    ids = await client.call_tool("list_ids")
                    self.assertFalse(loaded.is_error)
                    self.assertFalse(ids.is_error)
                    self.assertEqual(ids.structured_content, {"result": ["123"]})

            asyncio.run(exercise_stdio())
